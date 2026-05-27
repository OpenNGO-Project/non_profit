import frappe


def execute():
    if (
        not frappe.db.exists("DocType", "Donor")
        or not frappe.db.has_column("Donor", "customer")
        or not frappe.db.has_column("Donor", "email")
    ):
        return

    from non_profit.non_profit.doctype.donor.donor import (
        get_or_create_customer_for_donor,
    )

    donors = frappe.get_all(
        "Donor",
        filters={"customer": ["in", ["", None]], "email": ["not in", ["", None]]},
        pluck="name",
    )
    for donor in donors:
        try:
            get_or_create_customer_for_donor(donor)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "Donor customer email backfill failed"
            )
