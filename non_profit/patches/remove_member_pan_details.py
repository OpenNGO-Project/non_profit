import frappe
from frappe.model import delete_fields


def execute():
    _delete_member_pan_custom_field()

    fields_to_delete = {}
    if frappe.db.exists("DocType", "Member"):
        fields_to_delete["Member"] = ["pan_number"]

    if fields_to_delete:
        delete_fields(fields_to_delete, delete=1)

    frappe.clear_cache(doctype="Member")


def _delete_member_pan_custom_field():
    custom_field_name = "Member-pan_number"
    if not frappe.db.exists("Custom Field", custom_field_name):
        return

    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        frappe.delete_doc(
            "Custom Field",
            custom_field_name,
            ignore_permissions=True,
            force=True,
        )
    finally:
        frappe.set_user(original_user or "Administrator")
