from typing import Any

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import (
	PaymentEntry,
	get_bank_cash_account,
	get_reference_details,
)
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Sum
from frappe.utils.data import comma_or, flt, getdate


class NonProfitPaymentEntry(PaymentEntry):
	"""Import-compatible shell over ERPNext's PaymentEntry.

	This class intentionally carries NO behaviour. The Donation delta lives in
	the module-level ``doc_events`` handlers below (registered for
	``Payment Entry`` in ``non_profit/hooks.py``): ``override_doctype_class``
	resolves to the last installed app that overrides the doctype, so once
	``hrms`` (or any other app) registers its own Payment Entry class, a
	controller override from this app is silently inert and validation/sync
	behaviour would depend on install order. ``doc_events`` handlers fire for
	every Payment Entry regardless of which class wins, keeping the Donation
	delta deterministic.

	The class remains only so external callers can keep importing and
	constructing it; it must not grow required behaviour again.
	"""


def validate_donation_payment_entry_companies(doc, method: str | None = None) -> None:
	"""Reject cross-company Donation references before controller validation.

	The active Payment Entry controller resolves reference details during its
	own ``validate`` method. A cross-company row can make that generic lookup
	fail before normal ``validate`` doc-events run, so this invariant belongs in
	``before_validate`` as well as the full account check below.
	"""
	for donation_name in _donation_reference_names(doc):
		donation_company = frappe.db.get_value("Donation", donation_name, "company")
		if donation_company and doc.company != donation_company:
			frappe.throw(
				_("Donation {0} belongs to company {1}, but the Payment Entry company is {2}.").format(
					donation_name, donation_company, doc.company
				)
			)


def validate_donation_payment_entry_references(doc, method: str | None = None) -> None:
	"""``doc_events`` validate hook for Payment Entry.

	Runs after the active controller's own validate (erpnext base, hrms, or
	any future ``override_doctype_class`` winner) and enforces the
	Donation-side invariants the generic ERPNext path cannot express:

	- a Donor party may only allocate against Donation references,
	- company and Donor party account must match the referenced Donation (H2),
	- on submit, referenced Donations are locked in name order and the
	  cumulative allocation may not exceed the Donation amount (H1).

	No-ops fast when no allocated Donation reference rows exist.
	"""
	if doc.party_type == "Donor":
		for row in doc.get("references"):
			if not row.allocated_amount:
				continue
			if row.reference_doctype != "Donation":
				frappe.throw(_("Reference Doctype must be one of {0}").format(comma_or([_("Donation")])))

	_validate_donation_reference_accounts(doc)
	if doc.get("_action") == "submit":
		_lock_referenced_donations(doc)
		_validate_donation_allocation_totals(doc)


def sync_donation_reconciliation_state_on_payment_entry_change(doc, method: str | None = None) -> None:
	"""``doc_events`` on_change hook for Payment Entry (clearance-date sync)."""
	if doc.docstatus == 1:
		sync_donation_reconciliation_state_for_payment_entry(doc)


@frappe.whitelist()
def get_donation_payment_entry(
	dt: str,
	dn: str,
	party_amount: float | None = None,
	bank_account: str | None = None,
	bank_amount: float | None = None,
) -> Any:
	# Donation-only sibling of erpnext's get_payment_entry (which cannot map
	# the Donor party type). A caller-controlled doctype + name pair must not
	# become a generic permission-free document reader.
	if dt != "Donation":
		frappe.throw(_("Only Donation payment entries are supported here"))
	frappe.has_permission(dt, "read", doc=dn, throw=True)
	return _build_donation_payment_entry(dt, dn, party_amount, bank_account, bank_amount)


def _build_donation_payment_entry(
	dt: str,
	dn: str,
	party_amount: float | None = None,
	bank_account: str | None = None,
	bank_amount: float | None = None,
	posting_date: Any = None,
) -> Any:
	"""Build an unsaved Donation Payment Entry for trusted accounting flows."""
	if dt != "Donation":
		frappe.throw(_("Only Donation payment entries are supported here"))

	doc = frappe.get_doc(dt, dn)

	party_account = _expected_donation_party_account(doc)
	party_account_currency = doc.get("party_account_currency") or get_account_currency(party_account)
	grand_total = flt(doc.amount)
	outstanding_amount = _donation_outstanding_amount(doc.name)
	if outstanding_amount <= 0:
		frappe.throw(_("Donation {0} is fully allocated.").format(doc.name))

	payment_amount = flt(party_amount) or outstanding_amount
	if payment_amount > outstanding_amount:
		frappe.throw(
			_("Payment amount cannot exceed the remaining outstanding amount of {0}.").format(
				outstanding_amount
			)
		)

	# bank or cash
	bank = get_bank_cash_account(doc, bank_account)

	paid_amount = abs(payment_amount)
	if party_account_currency == bank.account_currency:
		received_amount = paid_amount
	else:
		received_amount = flt(bank_amount) or paid_amount * flt(doc.get("conversion_rate", 1))

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive"
	pe.company = doc.company
	pe.cost_center = doc.get("cost_center")
	pe.project = doc.get("project")
	pe.posting_date = getdate(posting_date) if posting_date else getdate()
	pe.mode_of_payment = doc.get("mode_of_payment")
	pe.party_type = "Donor"
	pe.party = doc.get("donor")
	pe.contact_person = doc.get("contact_person")
	pe.contact_email = doc.get("contact_email")

	pe.paid_from = party_account
	pe.paid_to = bank.account
	pe.paid_from_account_currency = party_account_currency
	pe.paid_to_account_currency = bank.account_currency
	pe.paid_amount = paid_amount
	pe.received_amount = received_amount
	pe.letter_head = doc.get("letter_head")

	pe.append(
		"references",
		{
			"reference_doctype": dt,
			"reference_name": dn,
			"bill_no": doc.get("bill_no"),
			"due_date": doc.get("due_date"),
			"total_amount": grand_total,
			"outstanding_amount": outstanding_amount,
			"allocated_amount": payment_amount,
		},
	)

	pe.setup_party_account_field()
	pe.set_missing_values()

	if party_account and bank:
		pe.set_exchange_rate()
		pe.set_amounts()

	return pe


def sync_donation_accounting_state_for_payment_entry(payment_entry, method: str | None = None) -> None:
	sync_donation_paid_state_for_payment_entry(payment_entry)
	sync_donation_reconciliation_state_for_payment_entry(payment_entry)


def sync_donation_paid_state_for_payment_entry(payment_entry) -> None:
	donation_names = _donation_names_for_payment_entry(payment_entry)
	for donation_name in donation_names:
		sync_donation_paid_state(donation_name)


def sync_donation_paid_state(donation_name: str) -> None:
	if not frappe.db.exists("Donation", donation_name):
		return

	donation_amount, current_paid, donor, major_gift = frappe.db.get_value(
		"Donation",
		donation_name,
		["amount", "paid", "donor", "major_gift"],
	)
	paid = 1 if _submitted_donation_payment_total(donation_name) >= flt(donation_amount) else 0
	if int(current_paid or 0) != paid:
		frappe.db.set_value("Donation", donation_name, "paid", paid, update_modified=False)
		# The paid flag feeds paid-only roll-ups (Donor lifetime giving +
		# major-donor flag, Major Gift closed amount). db.set_value fires no doc
		# hooks, so refresh them here — the same recompute the Donation
		# submit/cancel/trash ``on_donation_change`` hook performs.
		from non_profit.non_profit.major_gifts import (
			recompute_donor_giving,
			recompute_major_gift_closed,
		)

		if donor:
			recompute_donor_giving(donor)
		if major_gift:
			recompute_major_gift_closed(major_gift)

	sync_donation_advance_paid(donation_name)


def sync_donation_advance_paid(donation_name: str) -> None:
	"""Maintain ``Donation.advance_paid`` as the sum of submitted PE allocations.

	Together with ``Donation.grand_total`` (set on Donation validate) this
	mirrors Sales Invoice semantics so ERPNext's generic Payment Entry
	reference-details fallback computes ``outstanding = grand_total -
	advance_paid`` correctly under any ``override_doctype_class`` winner.
	Kept separate from the ``paid`` flag: Donations marked paid manually
	(without a Payment Entry) must not be reset by this sync.
	"""
	if not frappe.db.exists("Donation", donation_name):
		return
	# advance_paid is a custom field; guard for sites that have not migrated.
	if not frappe.get_meta("Donation").has_field("advance_paid"):
		return

	submitted_total = _submitted_donation_payment_total(donation_name)
	current_total = flt(frappe.db.get_value("Donation", donation_name, "advance_paid"))
	if current_total != submitted_total:
		frappe.db.set_value("Donation", donation_name, "advance_paid", submitted_total, update_modified=False)


def _submitted_donation_payment_total(donation_name: str, exclude_payment_entry: str | None = None) -> float:
	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	query = (
		frappe.qb.from_(payment_reference)
		.inner_join(payment_entry)
		.on(payment_entry.name == payment_reference.parent)
		.select(Sum(payment_reference.allocated_amount))
		.where(payment_entry.docstatus == 1)
		.where(payment_reference.reference_doctype == "Donation")
		.where(payment_reference.reference_name == donation_name)
	)
	if exclude_payment_entry:
		query = query.where(payment_entry.name != exclude_payment_entry)
	total = query.run()[0][0]
	return flt(total)


def _donation_outstanding_amount(donation_name: str, exclude_payment_entry: str | None = None) -> float:
	amount = flt(frappe.db.get_value("Donation", donation_name, "amount"))
	allocated = _submitted_donation_payment_total(donation_name, exclude_payment_entry)
	return max(amount - allocated, 0)


def _expected_donation_party_account(donation) -> str:
	configured_account = frappe.db.get_single_value("Non Profit Settings", "donation_debit_account")
	if (
		configured_account
		and frappe.db.get_value("Account", configured_account, "company") == donation.company
	):
		return configured_account
	return get_party_account("Donor", donation.donor, donation.company)


def _donation_reference_names(payment_entry) -> list[str]:
	return sorted(
		{
			row.reference_name
			for row in payment_entry.get("references")
			if row.reference_doctype == "Donation" and row.reference_name and flt(row.allocated_amount)
		}
	)


def _lock_referenced_donations(payment_entry) -> None:
	for donation_name in _donation_reference_names(payment_entry):
		frappe.db.get_value("Donation", donation_name, "name", for_update=True)


def _validate_donation_reference_accounts(payment_entry) -> None:
	for donation_name in _donation_reference_names(payment_entry):
		donation = frappe.get_doc("Donation", donation_name)
		if payment_entry.company != donation.company:
			frappe.throw(
				_("Donation {0} belongs to company {1}, but the Payment Entry company is {2}.").format(
					donation.name, donation.company, payment_entry.company
				)
			)

		expected_account = _expected_donation_party_account(donation)
		if payment_entry.party_account != expected_account:
			frappe.throw(
				_("Donation {0} requires Donor party account {1}, but the Payment Entry uses {2}.").format(
					donation.name, expected_account, payment_entry.party_account
				)
			)


def _validate_donation_allocation_totals(payment_entry) -> None:
	current_allocations = {}
	for row in payment_entry.get("references"):
		if row.reference_doctype == "Donation" and row.reference_name and flt(row.allocated_amount):
			current_allocations[row.reference_name] = current_allocations.get(row.reference_name, 0) + flt(
				row.allocated_amount
			)

	for donation_name in sorted(current_allocations):
		donation_amount = flt(frappe.db.get_value("Donation", donation_name, "amount"))
		already_allocated = _submitted_donation_payment_total(donation_name, payment_entry.name)
		if already_allocated + current_allocations[donation_name] > donation_amount:
			remaining = max(donation_amount - already_allocated, 0)
			frappe.throw(
				_("Donation {0} has only {1} remaining outstanding.").format(donation_name, remaining)
			)


def sync_donation_reconciliation_state_for_payment_entry(payment_entry) -> None:
	donation_names = _donation_names_for_payment_entry(payment_entry)
	for donation_name in donation_names:
		sync_donation_reconciliation_state(donation_name)


def sync_donation_reconciliation_state_for_payment_entry_name(
	payment_entry_name: str,
) -> None:
	for donation_name in _donation_names_for_payment_entry_name(payment_entry_name):
		sync_donation_reconciliation_state(donation_name)


def sync_donation_reconciliation_state(donation_name: str) -> None:
	if not frappe.db.exists("Donation", donation_name):
		return

	donation_meta = frappe.get_meta("Donation")
	if not donation_meta.has_field("reconciled"):
		return

	donation = frappe.db.get_value(
		"Donation",
		donation_name,
		["amount", "reconciled", "reconciled_on", "reconciled_payment_entry"],
		as_dict=True,
	)
	if not donation:
		return

	reconciled_payment = _submitted_reconciled_donation_payment_details(donation_name)
	reconciled = 1 if reconciled_payment.total >= flt(donation.amount) else 0
	reconciled_on = reconciled_payment.clearance_date if reconciled else None
	reconciled_payment_entry = reconciled_payment.payment_entry if reconciled else None

	updates = {}
	if int(donation.reconciled or 0) != reconciled:
		updates["reconciled"] = reconciled
	if donation_meta.has_field("reconciled_on") and donation.reconciled_on != reconciled_on:
		updates["reconciled_on"] = reconciled_on
	if (
		donation_meta.has_field("reconciled_payment_entry")
		and donation.reconciled_payment_entry != reconciled_payment_entry
	):
		updates["reconciled_payment_entry"] = reconciled_payment_entry

	if updates:
		frappe.db.set_value("Donation", donation_name, updates, update_modified=False)


def _donation_names_for_payment_entry(payment_entry) -> set[str]:
	return {
		row.reference_name
		for row in payment_entry.get("references")
		if row.reference_doctype == "Donation" and row.reference_name
	}


def _donation_names_for_payment_entry_name(payment_entry_name: str) -> set[str]:
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	rows = (
		frappe.qb.from_(payment_reference)
		.select(payment_reference.reference_name)
		.where(payment_reference.parent == payment_entry_name)
		.where(payment_reference.reference_doctype == "Donation")
		.where(payment_reference.reference_name.isnotnull())
	).run()
	return {row[0] for row in rows if row[0]}


def _submitted_reconciled_donation_payment_details(donation_name: str) -> frappe._dict:
	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	rows = (
		frappe.qb.from_(payment_reference)
		.inner_join(payment_entry)
		.on(payment_entry.name == payment_reference.parent)
		.select(
			payment_entry.name,
			payment_entry.clearance_date,
			payment_reference.allocated_amount,
		)
		.where(payment_entry.docstatus == 1)
		.where(payment_entry.clearance_date.isnotnull())
		.where(payment_entry.clearance_date != "0000-00-00")
		.where(payment_reference.reference_doctype == "Donation")
		.where(payment_reference.reference_name == donation_name)
		.orderby(payment_entry.clearance_date, order=Order.desc)
		.orderby(payment_entry.name, order=Order.desc)
	).run(as_dict=True)

	if not rows:
		return frappe._dict(total=0, clearance_date=None, payment_entry=None)

	return frappe._dict(
		total=sum(flt(row.allocated_amount) for row in rows),
		clearance_date=rows[0].clearance_date,
		payment_entry=rows[0].name,
	)


@frappe.whitelist()
def get_payment_reference_details(
	reference_doctype: str,
	reference_name: str,
	party_account_currency: str,
	party_type: str | None = None,
	party: str | None = None,
	current_payment_entry: str | None = None,
) -> dict[str, Any]:
	# Caller-controlled doctype + name: enforce read permission before
	# returning amounts/outstanding values from the referenced document.
	frappe.has_permission(reference_doctype, "read", doc=reference_name, throw=True)

	if reference_doctype != "Donation":
		# Everything except Donation keeps stock ERPNext behaviour.
		return get_reference_details(
			reference_doctype, reference_name, party_account_currency, party_type, party
		)

	ref_doc = frappe.get_doc(reference_doctype, reference_name)
	amount = flt(ref_doc.get("amount"))
	return frappe._dict(
		{
			"due_date": ref_doc.get("due_date"),
			"total_amount": amount,
			"outstanding_amount": _donation_outstanding_amount(reference_name, current_payment_entry),
			"exchange_rate": 1,
			"bill_no": None,
		}
	)


def audit_donation_payment_entry_invariants() -> dict[str, Any]:
	"""Report submitted Donation allocation/accounting inconsistencies without changing data."""
	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	donation = frappe.qb.DocType("Donation")
	rows = (
		frappe.qb.from_(payment_reference)
		.inner_join(payment_entry)
		.on(payment_entry.name == payment_reference.parent)
		.inner_join(donation)
		.on(donation.name == payment_reference.reference_name)
		.select(
			payment_entry.name.as_("payment_entry"),
			payment_entry.company.as_("payment_entry_company"),
			payment_entry.payment_type,
			payment_entry.paid_from,
			payment_entry.paid_to,
			payment_reference.reference_name.as_("donation"),
			payment_reference.allocated_amount,
			donation.amount.as_("donation_amount"),
			donation.company.as_("donation_company"),
			donation.donor,
		)
		.where(payment_entry.docstatus == 1)
		.where(payment_reference.reference_doctype == "Donation")
		.orderby(payment_reference.reference_name)
		.orderby(payment_entry.name)
	).run(as_dict=True)

	donation_totals = {}
	company_mismatches = []
	party_account_mismatches = []
	for row in rows:
		total = donation_totals.setdefault(
			row.donation,
			{
				"donation": row.donation,
				"donation_amount": flt(row.donation_amount),
				"submitted_allocation": 0,
				"payment_entries": [],
			},
		)
		total["submitted_allocation"] += flt(row.allocated_amount)
		total["payment_entries"].append(row.payment_entry)

		if row.payment_entry_company != row.donation_company:
			company_mismatches.append(
				{
					"donation": row.donation,
					"payment_entry": row.payment_entry,
					"donation_company": row.donation_company,
					"payment_entry_company": row.payment_entry_company,
				}
			)

		expected_account = _expected_donation_party_account(
			frappe._dict(company=row.donation_company, donor=row.donor)
		)
		party_account = row.paid_from if row.payment_type == "Receive" else row.paid_to
		if party_account != expected_account:
			party_account_mismatches.append(
				{
					"donation": row.donation,
					"payment_entry": row.payment_entry,
					"payment_type": row.payment_type,
					"expected_party_account": expected_account,
					"payment_entry_party_account": party_account,
				}
			)

	overallocated_donations = []
	for total in donation_totals.values():
		if total["submitted_allocation"] > total["donation_amount"]:
			total["excess_allocation"] = total["submitted_allocation"] - total["donation_amount"]
			overallocated_donations.append(total)

	return {
		"summary": {
			"submitted_donation_references": len(rows),
			"overallocated_donations": len(overallocated_donations),
			"company_mismatches": len(company_mismatches),
			"party_account_mismatches": len(party_account_mismatches),
		},
		"overallocated_donations": overallocated_donations,
		"company_mismatches": company_mismatches,
		"party_account_mismatches": party_account_mismatches,
	}
