import hmac

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
	if not _can_view_donation(donation):
		# Donation names are a sequential series; without the per-donation key
		# this page must not disclose donor name or amount.
		context.donation = None
		return context

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


def _can_view_donation(donation) -> bool:
	expected_key = (donation.get("confirmation_key") or "").strip()
	provided_key = (frappe.form_dict.get("key") or "").strip()
	if expected_key and provided_key and hmac.compare_digest(provided_key, expected_key):
		return True
	if frappe.session.user == "Guest":
		return False
	return frappe.has_permission("Donation", "read", doc=donation)
