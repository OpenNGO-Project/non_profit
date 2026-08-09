import frappe


def execute() -> None:
	indexes = (
		(
			"Recurring Donation",
			["payment_provider", "provider_account", "provider_subscription_id"],
			"recurring_provider_subscription_index",
		),
		(
			"Recurring Donation",
			["payment_provider", "provider_account", "provider_reference"],
			"recurring_provider_reference_index",
		),
		(
			"Donation",
			["recurring_donation", "payment_id"],
			"donation_recurring_payment_index",
		),
		(
			"Recurring Donation Installment",
			["recurring_donation", "installment_kind", "expected_date"],
			"recurring_installment_expected_index",
		),
		(
			"Recurring Donation Installment",
			["recurring_donation", "donation"],
			"recurring_installment_donation_index",
		),
	)
	for doctype, fields, index_name in indexes:
		if frappe.db.table_exists(doctype, cached=False) and all(
			frappe.db.has_column(doctype, fieldname) for fieldname in fields
		):
			frappe.db.add_index(doctype, fields, index_name=index_name)
