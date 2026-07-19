import frappe
from frappe.query_builder.functions import Sum
from frappe.utils.data import flt


def execute():
	"""Backfill Donation.grand_total / advance_paid for existing Donations.

	grand_total mirrors Donation.amount; advance_paid is the sum of submitted
	Payment Entry allocations against the Donation. Both fields feed ERPNext's
	generic Payment Entry reference-details fallback
	(outstanding = grand_total - advance_paid), which must be correct under
	any override_doctype_class winner (hrms shadows controller overrides on
	this bench).
	"""
	if not frappe.db.exists("DocType", "Donation"):
		return

	# post_model_sync runs before the after_migrate hook that creates the
	# custom fields, so ensure they exist first (same pattern as
	# convert_next_actions_to_tasks).
	from non_profit.setup import make_custom_fields

	make_custom_fields()

	if not (
		frappe.db.has_column("Donation", "grand_total") and frappe.db.has_column("Donation", "advance_paid")
	):
		return

	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	submitted_totals = dict(
		frappe.qb.from_(payment_reference)
		.inner_join(payment_entry)
		.on(payment_entry.name == payment_reference.parent)
		.select(payment_reference.reference_name, Sum(payment_reference.allocated_amount))
		.where(payment_entry.docstatus == 1)
		.where(payment_reference.reference_doctype == "Donation")
		.groupby(payment_reference.reference_name)
		.run()
	)

	for donation in frappe.get_all("Donation", fields=["name", "amount", "grand_total", "advance_paid"]):
		grand_total = flt(donation.amount)
		advance_paid = flt(submitted_totals.get(donation.name))
		if flt(donation.grand_total) == grand_total and flt(donation.advance_paid) == advance_paid:
			continue
		frappe.db.set_value(
			"Donation",
			donation.name,
			{"grand_total": grand_total, "advance_paid": advance_paid},
			update_modified=False,
		)
