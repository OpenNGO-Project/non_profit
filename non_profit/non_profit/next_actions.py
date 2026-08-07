# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Next-action Tasks for Donors and Major Gifts.

A moves-management "next action" can be an ERPNext ``Task`` linked back to its
parent through the ``Task.donor`` / ``Task.major_gift`` custom fields (created
in ``non_profit.setup``). Task-backed fields are derived from the earliest open
linked Task. Major Gifts may instead carry a manual ``next_action_date`` while
no Task is linked.
"""

import frappe
from frappe.utils import getdate

# Parent doctype -> the Task custom Link field that points back at it.
_PARENT_LINK_FIELD = {
	"Donor": "donor",
	"Major Gift": "major_gift",
}

# Parent doctype -> the User field used as the default assignee.
_ASSIGNEE_FIELD = {
	"Donor": "relationship_manager",
	"Major Gift": "relationship_manager",
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
	if parent_doctype == "Major Gift":
		task.donor = parent.donor
	task.insert(ignore_permissions=True)
	_share_task_with_user(task.name, frappe.session.user)

	assignee = (assignee or parent.get(_ASSIGNEE_FIELD.get(parent_doctype, "")) or "").strip()
	if assignee:
		_assign_task(task.name, assignee)

	for linked_doctype, linked_field in _PARENT_LINK_FIELD.items():
		if linked_name := task.get(linked_field):
			refresh_next_action(linked_doctype, linked_name)
	return task.name


def _assign_task(task_name: str, user: str) -> None:
	"""Assign the Task to a single User via Frappe's standard assignment (creates
	a ToDo, shares the Task when needed, and notifies)."""
	if not frappe.db.exists("User", user):
		return
	from frappe.desk.form.assign_to import DuplicateToDoError
	from frappe.desk.form.assign_to import add as assign_add

	_share_task_with_user(task_name, user)
	try:
		assign_add({"assign_to": [user], "doctype": "Task", "name": task_name})
	except DuplicateToDoError:
		# Already assigned to this user — nothing to do.
		pass


def _share_task_with_user(task_name: str, user: str) -> None:
	if not user or user in {"Administrator", "Guest"} or not frappe.db.exists("User", user):
		return
	if frappe.has_permission("Task", "write", doc=task_name, user=user):
		return
	frappe.share.add(
		"Task",
		task_name,
		user,
		read=1,
		write=1,
		share=0,
		notify=0,
		flags={"ignore_share_permission": True},
	)


def validate_task_links(doc, method: str | None = None) -> None:
	"""Keep the Donor link aligned when a Task belongs to a Major Gift."""
	if doc.get("major_gift"):
		major_gift = frappe.get_doc("Major Gift", doc.major_gift)
		if not doc.flags.ignore_permissions:
			major_gift.check_permission("write")
		doc.donor = major_gift.donor
	validate_task_parent_permissions(doc)


def validate_task_parent_permissions(doc, method: str | None = None) -> None:
	"""Require write access to every current or previous fundraising parent."""
	if doc.flags.ignore_permissions or frappe.session.user == "Administrator":
		return
	before = None if method == "on_trash" else doc.get_doc_before_save()
	parents: set[tuple[str, str]] = set()
	for parent_doctype, link_field in _PARENT_LINK_FIELD.items():
		if current := doc.get(link_field):
			parents.add((parent_doctype, current))
		if before and (previous := before.get(link_field)):
			parents.add((parent_doctype, previous))
	for parent_doctype, parent_name in parents:
		frappe.get_doc(parent_doctype, parent_name).check_permission("write")


def refresh_next_action(parent_doctype: str, parent_name: str, exclude_task: str | None = None) -> None:
	"""Recompute the parent's next-action fields from its earliest open Task.

	A Major Gift's unlinked manual follow-up date is preserved. Once a Task has
	controlled the fields, completing or deleting the last open Task clears them.
	"""
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
		current_task = frappe.db.get_value(parent_doctype, parent_name, "next_action_task")
		values = {"next_action": None, "next_action_task": None}
		if parent_doctype != "Major Gift" or current_task:
			values["next_action_date"] = None
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


@frappe.whitelist(methods=["POST"])
def set_next_action(
	doctype: str,
	name: str,
	subject: str,
	due_date: str | None = None,
	assignee: str | None = None,
) -> dict:
	"""Create, link, and assign a next-action Task for a Donor or Major Gift."""
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
