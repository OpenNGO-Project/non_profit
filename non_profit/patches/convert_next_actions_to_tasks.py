import frappe


def execute():
	"""Convert existing free-text next_action / next_action_date values into
	linked Tasks (the new source of truth). Idempotent:
	rows that already have an open linked Task are skipped."""
	# post_model_sync runs before the after_migrate hook that creates the Task
	# custom fields, so ensure they exist before we link Tasks to parents.
	from non_profit.setup import make_custom_fields

	make_custom_fields()

	from non_profit.non_profit.next_actions import (
		_PARENT_LINK_FIELD,
		_TERMINAL_TASK_STATUSES,
		create_next_action_task,
	)

	for doctype, link_field in _PARENT_LINK_FIELD.items():
		if not frappe.db.exists("DocType", doctype) or not frappe.db.has_column(doctype, "next_action"):
			continue
		rows = frappe.get_all(doctype, fields=["name", "next_action", "next_action_date"])
		for row in rows:
			text = (row.next_action or "").strip()
			if not text:
				continue
			if frappe.db.exists(
				"Task", {link_field: row.name, "status": ["not in", _TERMINAL_TASK_STATUSES]}
			):
				continue
			create_next_action_task(doctype, row.name, text, row.next_action_date)
