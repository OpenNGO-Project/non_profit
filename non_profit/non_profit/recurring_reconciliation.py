# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Expected-versus-actual evidence for Recurring Donations.

Reconciliation materializes schedule expectations and links ordinary Donation
records reported by providers or generated for local schedules. It never calls a
payment provider and never initiates a charge.
"""

from math import isfinite

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_years, cstr, flt, getdate, now_datetime, nowdate

MAX_EXPECTED_INSTALLMENTS = 1200
MAX_RECONCILIATION_DONATIONS = 5000
RECONCILIATION_BATCH_SIZE = 100
TERMINAL_SCHEDULE_STATUSES = ("Payment Failed", "Cancelled")
REVERSAL_SOURCES = {
	"Payment Entry Cancellation": "Accounting",
	"Full Refund": "Provider",
	"Chargeback": "Provider",
}


def reconcile_recurring_donation(
	recurring_donation: str,
	*,
	as_of=None,
	through_date=None,
) -> dict:
	"""Lock one schedule and deterministically rebuild its installment evidence."""
	if not frappe.db.exists("DocType", "Recurring Donation Installment"):
		return {}
	schedule = frappe.get_doc("Recurring Donation", recurring_donation, for_update=True)
	from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
		validate_recurring_donation_currency,
	)

	validate_recurring_donation_currency(schedule)
	as_of = getdate(as_of or nowdate())
	horizon = _reconciliation_horizon(schedule, as_of, through_date)
	expected_dates = _expected_dates(schedule, horizon)
	installments = _load_installments(schedule.name)
	expected_by_date = {
		getdate(row.expected_date): row for row in installments if row.installment_kind == "Expected"
	}
	for expected_date in expected_dates:
		installment = expected_by_date.get(expected_date)
		if not installment:
			installment = frappe.new_doc("Recurring Donation Installment")
			installment.update(
				{
					"recurring_donation": schedule.name,
					"installment_kind": "Expected",
					"expected_date": expected_date,
					"expected_amount": schedule.amount,
					"currency": schedule.currency,
					"status": "Expected",
				}
			)
			_save_installment(installment)
			expected_by_date[expected_date] = installment
		else:
			updates = {}
			if installment.is_retired:
				updates.update({"is_retired": 0, "retired_on": None})
			if (
				not installment.donation
				and expected_date > as_of
				and schedule.status not in TERMINAL_SCHEDULE_STATUSES
			):
				updates.update({"expected_amount": schedule.amount, "currency": schedule.currency})
			if updates:
				_update_installment(installment, updates)

	expected_date_set = set(expected_dates)
	for expected_date, installment in expected_by_date.items():
		if expected_date not in expected_date_set and not installment.is_retired:
			_update_installment(
				installment,
				{"is_retired": 1, "retired_on": now_datetime()},
			)

	installments = _load_installments(schedule.name)
	donations = frappe.get_all(
		"Donation",
		filters={"recurring_donation": schedule.name, "docstatus": [">", 0]},
		fields=["name", "date", "amount", "paid", "docstatus", "creation"],
		order_by="date asc, creation asc, name asc",
		limit_page_length=MAX_RECONCILIATION_DONATIONS + 1,
	)
	if len(donations) > MAX_RECONCILIATION_DONATIONS:
		frappe.throw(
			_("Recurring Donation {0} exceeds the reconciliation Donation limit.").format(schedule.name)
		)
	_deterministically_assign_donations(schedule, installments, donations)

	installments = _load_installments(schedule.name)
	_reconcile_rows(schedule, installments, donations, as_of)
	installments = _load_installments(schedule.name)
	rollup = _update_schedule_rollup(schedule, installments, as_of)
	return {"recurring_donation": schedule.name, **rollup}


def reconcile_recurring_donations() -> None:
	"""Daily repair of due/missed/variance state for every schedule."""
	if not frappe.db.exists("DocType", "Recurring Donation Installment"):
		return
	last_name = ""
	while True:
		names = frappe.get_all(
			"Recurring Donation",
			filters={"name": [">", last_name]} if last_name else None,
			pluck="name",
			order_by="name asc",
			limit_page_length=RECONCILIATION_BATCH_SIZE,
		)
		if not names:
			break
		for name in names:
			try:
				reconcile_recurring_donation(name)
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"Recurring Donation reconciliation failed: {name}")
		last_name = names[-1]


def record_recurring_installment_reversal(
	donation: str,
	*,
	reversal_kind: str,
	reversal_reference: str,
	reversal_date=None,
	reversal_amount: float | None = None,
) -> dict:
	"""Record one immutable, full accounting or provider reversal.

	Provider apps call this neutral API after authenticating and correlating their
	event. Payment Entry hooks call it only after an approved cancellation leaves
	no submitted allocation. Partial or unidentified events remain review evidence
	outside this ledger and cannot turn an installment into ``Reversed``.
	"""
	if not frappe.db.exists("DocType", "Recurring Donation Installment"):
		return {}
	donation = cstr(donation).strip()
	reversal_kind = cstr(reversal_kind).strip()
	reversal_reference = cstr(reversal_reference).strip()
	if reversal_kind not in REVERSAL_SOURCES:
		frappe.throw(_("Unsupported recurring installment reversal kind."))
	if not reversal_reference or len(reversal_reference) > 140:
		frappe.throw(_("Recurring installment reversal requires a valid reference."))

	schedule_name = frappe.db.get_value("Donation", donation, "recurring_donation")
	if not schedule_name:
		frappe.throw(_("The reversed Donation is not linked to a recurring schedule."))
	reconcile_recurring_donation(schedule_name)

	donation_doc = frappe.get_doc("Donation", donation, for_update=True)
	if cstr(donation_doc.recurring_donation).strip() != schedule_name:
		frappe.throw(_("The reversed Donation changed recurring schedule during reconciliation."))

	installment = frappe.qb.DocType("Recurring Donation Installment")
	installment_names = (
		frappe.qb.from_(installment)
		.select(installment.name)
		.where(installment.recurring_donation == schedule_name)
		.where(installment.donation == donation)
		.orderby(installment.name)
		.limit(2)
		.for_update()
	).run(pluck=True)
	if len(installment_names) != 1:
		frappe.throw(_("The reversed Donation does not match exactly one recurring installment."))

	current = frappe.get_doc("Recurring Donation Installment", installment_names[0], for_update=True)
	actual_amount = flt(current.actual_amount)
	if not current.actual_date or actual_amount <= 0:
		frappe.throw(_("The recurring installment has no original actual settlement snapshot."))
	amount = flt(reversal_amount)
	if not isfinite(amount) or amount <= 0 or abs(amount - actual_amount) >= 0.000001:
		frappe.throw(_("Only a full recurring installment reversal can be recorded."))
	if current.reversal_kind:
		matching_replay = (
			current.reversal_source == REVERSAL_SOURCES[reversal_kind]
			and current.reversal_kind == reversal_kind
			and cstr(current.reversal_reference).strip() == reversal_reference
			and abs(flt(current.reversal_amount) - amount) < 0.000001
			and (not reversal_date or getdate(current.reversal_date) == getdate(reversal_date))
		)
		if not matching_replay:
			frappe.throw(_("The reversal conflicts with existing immutable installment evidence."))
		return _reversal_result(current)
	_update_installment(
		current,
		{
			"reversal_source": REVERSAL_SOURCES[reversal_kind],
			"reversal_kind": reversal_kind,
			"reversal_reference": reversal_reference,
			"reversal_date": getdate(reversal_date or nowdate()),
			"reversal_amount": amount,
			"reversal_recorded_on": now_datetime(),
		},
	)
	reconcile_recurring_donation(schedule_name)
	current = frappe.get_doc("Recurring Donation Installment", current.name)
	return _reversal_result(current)


def _reversal_result(installment) -> dict:
	return {
		"installment": installment.name,
		"status": installment.status,
		"reversal_source": installment.reversal_source,
		"reversal_kind": installment.reversal_kind,
		"reversal_reference": installment.reversal_reference,
	}


def _reconciliation_horizon(schedule, as_of, through_date):
	horizon = as_of
	for value in (through_date, schedule.provider_next_payment, schedule.next_date):
		if value and getdate(value) > horizon:
			horizon = getdate(value)
	if schedule.status in TERMINAL_SCHEDULE_STATUSES and schedule.closed_on:
		horizon = min(horizon, getdate(schedule.closed_on))
	if schedule.end_date:
		horizon = min(horizon, getdate(schedule.end_date))
	return horizon


def _expected_dates(schedule, horizon) -> list:
	if not schedule.start_date or not schedule.frequency:
		return []
	current = getdate(schedule.start_date)
	dates = []
	while current <= horizon:
		dates.append(current)
		if len(dates) > MAX_EXPECTED_INSTALLMENTS:
			frappe.throw(
				_("Recurring Donation {0} exceeds the reconciliation installment limit.").format(
					schedule.name
				)
			)
		if schedule.frequency == "Monthly":
			current = add_months(current, 1)
		elif schedule.frequency == "Quarterly":
			current = add_months(current, 3)
		elif schedule.frequency == "Yearly":
			current = add_years(current, 1)
		else:
			frappe.throw(_("Unsupported Recurring Donation frequency {0}.").format(schedule.frequency))
	return dates


def _load_installments(schedule_name: str):
	return frappe.get_all(
		"Recurring Donation Installment",
		filters={"recurring_donation": schedule_name},
		fields=[
			"name",
			"installment_kind",
			"status",
			"expected_date",
			"expected_amount",
			"currency",
			"donation",
			"actual_date",
			"actual_amount",
			"amount_variance",
			"reconciled_on",
			"is_retired",
			"retired_on",
			"reversal_source",
			"reversal_kind",
			"reversal_reference",
			"reversal_date",
			"reversal_amount",
			"reversal_recorded_on",
		],
		order_by="expected_date asc, creation asc, name asc",
		limit_page_length=0,
	)


def _deterministically_assign_donations(schedule, installments, donations) -> None:
	donation_by_name = {row.name: row for row in donations}
	assigned = {row.donation for row in installments if row.donation and row.donation in donation_by_name}
	expected = [row for row in installments if row.installment_kind == "Expected" and not row.is_retired]

	for donation in donations:
		if donation.name in assigned:
			continue
		if donation.docstatus == 2 and not donation.paid:
			continue
		exact = next(
			(
				row
				for row in expected
				if not row.donation and getdate(row.expected_date) == getdate(donation.date)
			),
			None,
		)
		if exact:
			_update_installment(exact, {"donation": donation.name})
			assigned.add(donation.name)

	for donation in donations:
		if donation.name in assigned or donation.docstatus != 1 or not donation.paid:
			continue
		eligible = [
			row
			for row in expected
			if not row.donation and getdate(row.expected_date) <= getdate(donation.date)
		]
		if eligible:
			installment = eligible[-1]
			_update_installment(installment, {"donation": donation.name})
			assigned.add(donation.name)

	unexpected_by_donation = {
		row.donation: row for row in installments if row.installment_kind == "Unexpected" and row.donation
	}
	for donation in donations:
		if donation.name in assigned or not donation.paid:
			continue
		if donation.name in unexpected_by_donation:
			continue
		installment = frappe.new_doc("Recurring Donation Installment")
		installment.update(
			{
				"recurring_donation": schedule.name,
				"installment_kind": "Unexpected",
				"status": "Unexpected",
				"expected_date": donation.date,
				"expected_amount": 0,
				"currency": schedule.currency,
				"donation": donation.name,
			}
		)
		_save_installment(installment)


def _reconcile_rows(schedule, installments, donations, as_of) -> None:
	donation_by_name = {row.name: row for row in donations}
	closed_date = getdate(schedule.closed_on) if schedule.closed_on else None
	natural_end = schedule.closure_category == "Schedule" and schedule.closure_reason == "End date reached"
	for installment in installments:
		donation = donation_by_name.get(installment.donation)
		expected_amount = flt(installment.expected_amount)
		actual_amount = flt(installment.actual_amount)
		actual_date = getdate(installment.actual_date) if installment.actual_date else None
		if not actual_date and donation and donation.docstatus == 1 and donation.paid:
			actual_amount = flt(donation.amount)
			actual_date = getdate(donation.date)

		if installment.reversal_kind:
			status = "Reversed"
			variance = -actual_amount if installment.installment_kind == "Unexpected" else -expected_amount
		elif installment.installment_kind == "Unexpected":
			status = "Unexpected"
			variance = actual_amount
		elif actual_date:
			variance = actual_amount - expected_amount
			status = "Settled" if abs(variance) < 0.000001 else "Variance"
		elif installment.is_retired:
			status = "Cancelled"
			variance = 0.0
		elif (
			schedule.status == "Cancelled"
			and closed_date
			and not natural_end
			and getdate(installment.expected_date) >= closed_date
		):
			status = "Cancelled"
			variance = 0.0
		elif (
			schedule.status == "Payment Failed"
			and closed_date
			and getdate(installment.expected_date) <= closed_date
		):
			status = "Missed"
			variance = -expected_amount
		elif getdate(installment.expected_date) < as_of:
			status = "Missed"
			variance = -expected_amount
		else:
			status = "Expected"
			variance = 0.0

		_update_installment(
			installment,
			{
				"status": status,
				"actual_date": actual_date,
				"actual_amount": actual_amount,
				"amount_variance": variance,
			},
		)


def _update_schedule_rollup(schedule, installments, as_of) -> dict:
	active_expected = [
		row for row in installments if row.installment_kind == "Expected" and not row.is_retired
	]
	due_expected = [
		row for row in active_expected if row.status != "Cancelled" and getdate(row.expected_date) <= as_of
	]
	actual = [
		row
		for row in installments
		if row.status in ("Settled", "Variance", "Unexpected") and flt(row.actual_amount) > 0
	]
	active_rows = [row for row in installments if row.installment_kind == "Unexpected" or not row.is_retired]
	rollup = {
		"expected_installment_count": len([row for row in active_expected if row.status != "Cancelled"]),
		"actual_installment_count": len(actual),
		"missed_installment_count": len([row for row in active_expected if row.status == "Missed"]),
		"variance_installment_count": len(
			[row for row in active_rows if row.status in ("Variance", "Unexpected", "Reversed")]
		),
		"due_expected_amount": sum(flt(row.expected_amount) for row in due_expected),
		"settled_actual_amount": sum(flt(row.actual_amount) for row in actual),
		"settlement_variance": sum(flt(row.amount_variance) for row in due_expected)
		+ sum(
			flt(row.amount_variance)
			for row in installments
			if row.installment_kind == "Unexpected"
			and row.status != "Reversed"
			and getdate(row.expected_date) <= as_of
		),
		"last_reconciled_on": now_datetime(),
	}
	frappe.db.set_value("Recurring Donation", schedule.name, rollup, update_modified=False)
	return rollup


def _save_installment(installment) -> None:
	from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
		allow_reconciliation_write,
	)

	installment.reconciled_on = now_datetime()
	allow_reconciliation_write(installment)
	installment.insert(ignore_permissions=True)


def _update_installment(installment, values: dict) -> None:
	current = frappe.get_doc("Recurring Donation Installment", installment.name)
	changed = False
	for fieldname, value in values.items():
		current_value = current.get(fieldname)
		if fieldname in {"expected_amount", "actual_amount", "amount_variance"}:
			is_changed = abs(flt(current_value) - flt(value)) >= 0.000001
		elif fieldname in {"expected_date", "actual_date"}:
			is_changed = (getdate(current_value) if current_value else None) != (
				getdate(value) if value else None
			)
		else:
			is_changed = cstr(current_value) != cstr(value)
		if is_changed:
			current.set(fieldname, value)
			changed = True
	if not changed:
		return
	current.reconciled_on = now_datetime()
	from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
		allow_reconciliation_write,
	)

	allow_reconciliation_write(current)
	current.save(ignore_permissions=True)
	if isinstance(installment, Document):
		for fieldname, value in values.items():
			installment.set(fieldname, value)
		installment.set("reconciled_on", current.reconciled_on)
	else:
		for fieldname, value in values.items():
			installment[fieldname] = value
		installment.reconciled_on = current.reconciled_on
