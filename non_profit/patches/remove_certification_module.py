"""Remove the unused Certification module.

Certification Application / Certified Consultant and their public web forms
were inherited from upstream and are not used by any dependent app. The code
and fixtures were deleted; this patch removes the doctypes, their tables, and
the web forms from installed sites.
"""

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
		table_name = f"tab{doctype}"
		if frappe.db.table_exists(table_name, cached=False):
			frappe.db.sql_ddl(f"drop table `{table_name}`")

	frappe.clear_cache()
