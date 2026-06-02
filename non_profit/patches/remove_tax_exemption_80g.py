import frappe
from frappe.model import delete_fields


PRINT_FORMATS = (
    "80G Certificate for Donation",
    "80G Certificate for Membership",
)

DOCTYPES = (
    "Tax Exemption 80G Certificate",
    "Tax Exemption 80G Certificate Detail",
)

COMPANY_CUSTOM_FIELDS = (
    "Company-non_profit_section",
    "Company-company_80g_number",
    "Company-with_effect_from",
    "Company-non_profit_column_break",
    "Company-pan_details",
)

COMPANY_DATA_FIELDS = (
    "company_80g_number",
    "with_effect_from",
    "pan_details",
)


def execute():
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        _delete_print_formats()
        _delete_80g_doctypes()
        _delete_company_80g_custom_fields()
        _drop_80g_tables()
    finally:
        frappe.set_user(original_user or "Administrator")

    frappe.clear_cache()


def _delete_print_formats():
    for print_format in PRINT_FORMATS:
        if frappe.db.exists("Print Format", print_format):
            frappe.delete_doc(
                "Print Format",
                print_format,
                ignore_permissions=True,
                force=True,
            )


def _delete_80g_doctypes():
    if frappe.db.exists("DocType", "Tax Exemption 80G Certificate"):
        frappe.db.delete("Tax Exemption 80G Certificate")
    if frappe.db.exists("DocType", "Tax Exemption 80G Certificate Detail"):
        frappe.db.delete("Tax Exemption 80G Certificate Detail")

    for doctype in DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            frappe.delete_doc(
                "DocType",
                doctype,
                ignore_permissions=True,
                force=True,
            )


def _delete_company_80g_custom_fields():
    for custom_field in COMPANY_CUSTOM_FIELDS:
        if frappe.db.exists("Custom Field", custom_field):
            frappe.delete_doc(
                "Custom Field",
                custom_field,
                ignore_permissions=True,
                force=True,
            )

    if frappe.db.exists("DocType", "Company"):
        delete_fields({"Company": list(COMPANY_DATA_FIELDS)}, delete=1)


def _drop_80g_tables():
    for doctype in DOCTYPES:
        table_name = f"tab{doctype}"
        if frappe.db.table_exists(doctype, cached=False):
            frappe.db.commit()
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table_name}`")
