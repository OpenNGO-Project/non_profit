"""Retire Donor Interaction and reduce the Major Gift pipeline (16.11.0)."""

import frappe

RETIRED_DOCTYPE = "Donor Interaction"
RETIRED_TASK_FIELD = "donor_interaction"
STAGE_RENAMES = {
	"Identification": "Qualification",
	"Stewardship": "Solicitation",
}


def execute() -> None:
	_map_major_gift_stages()
	_delete_interaction_tasks()
	_remove_interaction_navigation()
	_remove_interaction_permissions()
	_remove_task_custom_field()
	_remove_interaction_doctype()
	frappe.clear_cache()


def _map_major_gift_stages() -> None:
	if not frappe.db.table_exists("Major Gift", cached=False):
		return
	for old_stage, new_stage in STAGE_RENAMES.items():
		frappe.db.set_value("Major Gift", {"stage": old_stage}, "stage", new_stage, update_modified=False)


def _delete_interaction_tasks() -> None:
	if not (
		frappe.db.table_exists("Task", cached=False) and frappe.db.has_column("Task", RETIRED_TASK_FIELD)
	):
		return
	for task_name in frappe.get_all(
		"Task",
		filters={RETIRED_TASK_FIELD: ["is", "set"]},
		pluck="name",
		order_by="name asc",
	):
		frappe.delete_doc("Task", task_name, force=True, ignore_missing=True)


def _remove_interaction_navigation() -> None:
	if frappe.db.exists("DocType", "Workspace Link"):
		frappe.db.delete("Workspace Link", {"link_type": "DocType", "link_to": RETIRED_DOCTYPE})
	if frappe.db.exists("DocType", "Workspace Sidebar Item"):
		frappe.db.delete(
			"Workspace Sidebar Item",
			{"link_type": "DocType", "link_to": RETIRED_DOCTYPE},
		)


def _remove_task_custom_field() -> None:
	custom_field = f"Task-{RETIRED_TASK_FIELD}"
	if frappe.db.exists("Custom Field", custom_field):
		frappe.delete_doc("Custom Field", custom_field, force=True, ignore_missing=True)


def _remove_interaction_permissions() -> None:
	if frappe.db.exists("DocType", "Custom DocPerm"):
		frappe.db.delete("Custom DocPerm", {"parent": RETIRED_DOCTYPE})


def _remove_interaction_doctype() -> None:
	if frappe.db.exists("DocType", RETIRED_DOCTYPE):
		frappe.delete_doc("DocType", RETIRED_DOCTYPE, force=True, ignore_missing=True)
	if frappe.db.table_exists(RETIRED_DOCTYPE, cached=False):
		frappe.db.sql_ddl(f"drop table `tab{RETIRED_DOCTYPE}`")
