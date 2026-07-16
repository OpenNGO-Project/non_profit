# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Next-action Tasks for Major Gift and Donor Interaction.

A moves-management "next action" is an ERPNext ``Task`` linked back to its
parent through the ``Task.major_gift`` / ``Task.donor_interaction`` custom
fields (created in ``non_profit.setup``). Each parent's read-only
``next_action`` / ``next_action_date`` / ``next_action_task`` fields are
*derived* from the earliest open linked Task, so the pipeline list and reports
keep working off those fieldnames.
"""

import frappe
from frappe.utils import getdate

# Parent doctype -> the Task custom Link field that points back at it.
_PARENT_LINK_FIELD = {
	"Major Gift": "major_gift",
	"Donor Interaction": "donor_interaction",
}

# Parent doctype -> the User field used as the default assignee.
_ASSIGNEE_FIELD = {
	"Major Gift": "relationship_manager",
	"Donor Interaction": "staff",
}

# A Task no longer counts as an open "next action" once it reaches one of these.
_TERMINAL_TASK_STATUSES = ("Completed", "Cancelled", "Template")


def create_next_action_task(
	parent_doctype: str,
	parent_name: str,
	subject: str,
	due_date=None,
	assignee: str | None = None,
) -> str:
	"""Create a Task for the parent's next action, link + assign it, refresh the
	parent's derived next-action fields, and return the Task name."""
	link_field = _PARENT_LINK_FIELD.get(parent_doctype)
	if not link_field:
		frappe.throw(frappe._("Next actions are not supported for {0}.").format(parent_doctype))

	subject = (subject or "").strip()
	if not subject:
		frappe.throw(frappe._("A next action description is required."))

	parent = frappe.get_doc(parent_doctype, parent_name)

	task = frappe.new_doc("Task")
	task.subject = subject
	task.status = "Open"
	if due_date:
		task.exp_end_date = getdate(due_date)
	task.set(link_field, parent_name)
	# A task created from a Donor Interaction also rolls up to its Major Gift.
	if parent_doctype == "Donor Interaction" and parent.get("major_gift"):
		task.major_gift = parent.major_gift
	task.insert(ignore_permissions=True)

	assignee = (assignee or parent.get(_ASSIGNEE_FIELD.get(parent_doctype, "")) or "").strip()
	if assignee:
		_assign_task(task.name, assignee)

	refresh_next_action(parent_doctype, parent_name)
	if parent_doctype != "Major Gift" and task.get("major_gift"):
		refresh_next_action("Major Gift", task.major_gift)
	return task.name


def _assign_task(task_name: str, user: str) -> None:
	"""Assign the Task to a single User via Frappe's standard assignment (creates
	a ToDo + notifies). Best-effort: a failed assignment must not lose the Task."""
	if not frappe.db.exists("User", user):
		return
	from frappe.desk.form.assign_to import add as assign_add

	try:
		assign_add({"assign_to": [user], "doctype": "Task", "name": task_name})
	except frappe.ValidationError:
		# Already assigned to this user — nothing to do.
		pass
	except Exception:
		frappe.log_error(title="Major Gift next-action task assignment failed")


def refresh_next_action(parent_doctype: str, parent_name: str, exclude_task: str | None = None) -> None:
	"""Recompute the parent's read-only ``next_action`` / ``next_action_date`` /
	``next_action_task`` from its earliest open linked Task."""
	link_field = _PARENT_LINK_FIELD.get(parent_doctype)
	if not link_field or not parent_name or not frappe.db.exists(parent_doctype, parent_name):
		return

	filters: dict = {link_field: parent_name, "status": ["not in", _TERMINAL_TASK_STATUSES]}
	if exclude_task:
		filters["name"] = ["!=", exclude_task]
	rows = frappe.get_all(
		"Task",
		filters=filters,
		fields=["name", "subject", "exp_end_date"],
		order_by="exp_end_date asc, creation asc",
		limit=1,
	)
	if rows:
		task = rows[0]
		values = {
			"next_action": task.subject,
			"next_action_date": task.exp_end_date,
			"next_action_task": task.name,
		}
	else:
		values = {"next_action": None, "next_action_date": None, "next_action_task": None}
	frappe.db.set_value(parent_doctype, parent_name, values, update_modified=False)


def on_task_change(doc, method: str | None = None) -> None:
	"""``Task`` on_update / on_trash hook: refresh every parent the Task points at
	(plus any parent it just stopped pointing at)."""
	# on_trash runs before the row is deleted, so exclude this Task from the recompute.
	exclude = doc.name if method == "on_trash" else None
	before = doc.get_doc_before_save() if method != "on_trash" else None

	parents: set[tuple[str, str]] = set()
	for parent_doctype, link_field in _PARENT_LINK_FIELD.items():
		current = doc.get(link_field)
		if current:
			parents.add((parent_doctype, current))
		if before and before.get(link_field) and before.get(link_field) != current:
			parents.add((parent_doctype, before.get(link_field)))

	for parent_doctype, parent_name in parents:
		refresh_next_action(parent_doctype, parent_name, exclude_task=exclude)


@frappe.whitelist()
def set_next_action(
	doctype: str,
	name: str,
	subject: str,
	due_date: str | None = None,
	assignee: str | None = None,
) -> dict:
	"""Create + link + assign a next-action Task for a Major Gift / Donor
	Interaction. Gated by write permission on the parent."""
	if doctype not in _PARENT_LINK_FIELD:
		frappe.throw(frappe._("Next actions are not supported for {0}.").format(doctype))
	if not frappe.has_permission(doctype, "write", doc=name):
		frappe.throw(
			frappe._("Not permitted to update {0} {1}.").format(doctype, name), frappe.PermissionError
		)

	task_name = create_next_action_task(doctype, name, subject, due_date, assignee)
	values = frappe.db.get_value(
		doctype, name, ["next_action", "next_action_date", "next_action_task"], as_dict=True
	)
	return {"task": task_name, **(values or {})}
