"""Complete Certification cleanup for sites that ran the original patch."""

import frappe

WEB_FORMS = (
	"certification-application",
	"certification-application-usd",
)

DOCTYPES = (
	"Certification Application",
	"Certified Consultant",
)


def execute():
	for web_form in frappe.get_all(
		"Web Form",
		filters={"module": "Non Profit", "doc_type": ["in", list(DOCTYPES)]},
		pluck="name",
	):
		frappe.delete_doc("Web Form", web_form, ignore_permissions=True, force=True)
	for web_form in WEB_FORMS:
		if frappe.db.exists("Web Form", web_form):
			frappe.delete_doc("Web Form", web_form, ignore_permissions=True, force=True)

	for doctype in DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)
		if frappe.db.table_exists(doctype, cached=False):
			frappe.db.sql_ddl(f"drop table `tab{doctype}`")

	frappe.clear_cache()
