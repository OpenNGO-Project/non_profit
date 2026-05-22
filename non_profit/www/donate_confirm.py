import frappe
from frappe import _

from non_profit.non_profit.doctype.donation.donation import (
    authorize_mock_donation_payment,
    mock_donation_payments_enabled,
)


no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False

    donation_name = frappe.form_dict.get("donation")
    if not donation_name:
        context.donation = None
        return context

    if not frappe.db.exists("Donation", donation_name):
        context.donation = None
        return context

    donation = frappe.get_doc("Donation", donation_name)
    context.mock_payments_enabled = mock_donation_payments_enabled()

    if frappe.request and frappe.request.method == "POST" and not donation.paid:
        if not context.mock_payments_enabled:
            context.error = _("Demo payments are disabled on this site.")
            context.donation = donation
            return context
        authorize_mock_donation_payment(donation.name)
        donation.reload()

    context.donation = donation
    return context
