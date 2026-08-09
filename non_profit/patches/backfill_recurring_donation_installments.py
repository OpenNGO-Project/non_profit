import frappe
from frappe import _
from frappe.utils import cstr

BATCH_SIZE = 100


def execute() -> None:
	if not frappe.db.exists("DocType", "Recurring Donation Installment"):
		return
	_assert_company_currency_compatibility()
	from non_profit.non_profit.recurring_reconciliation import reconcile_recurring_donation

	last_name = ""
	while True:
		names = frappe.get_all(
			"Recurring Donation",
			filters={"name": [">", last_name]} if last_name else None,
			pluck="name",
			order_by="name asc",
			limit_page_length=BATCH_SIZE,
		)
		if not names:
			break
		for name in names:
			reconcile_recurring_donation(name)
		last_name = names[-1]


def _assert_company_currency_compatibility() -> None:
	"""Fail before writing evidence instead of relabelling legacy amounts."""
	company_currencies = {
		row.name: cstr(row.default_currency).strip()
		for row in frappe.get_all(
			"Company",
			fields=["name", "default_currency"],
			limit_page_length=0,
		)
	}
	mismatches = []
	last_name = ""
	while len(mismatches) < 20:
		rows = frappe.get_all(
			"Recurring Donation",
			filters={"name": [">", last_name]} if last_name else None,
			fields=["name", "company", "currency"],
			order_by="name asc",
			limit_page_length=BATCH_SIZE,
		)
		if not rows:
			break
		for row in rows:
			company_currency = company_currencies.get(row.company, "")
			if not company_currency or cstr(row.currency).strip() != company_currency:
				mismatches.append(
					f"{row.name} ({cstr(row.currency).strip() or '-'} / {company_currency or '-'})"
				)
				if len(mismatches) == 20:
					break
		last_name = rows[-1].name
	if mismatches:
		frappe.throw(
			_(
				"Recurring Donation currency does not match Company default currency. "
				"Correct the legacy schedules before backfill: {0}"
			).format(", ".join(mismatches))
		)
