import frappe
from frappe.model import delete_fields


def execute():
	if frappe.db.exists("DocType", "Membership"):
		delete_fields({"Membership": ["company"]}, delete=1)

	frappe.clear_cache(doctype="Membership")
