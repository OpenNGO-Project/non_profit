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
from frappe.utils.data import flt, getdate


class NonProfitPaymentEntry(PaymentEntry):
	"""Donor-aware Payment Entry.

	Minimal delta over ERPNext's PaymentEntry: support the Donor party type
	(paying against Donation references) and keep the linked Donations' paid /
	reconciliation state in sync. Everything else defers to super().
	"""

	def on_submit(self):
		super().on_submit()
		sync_donation_accounting_state_for_payment_entry(self)

	def on_cancel(self):
		super().on_cancel()
		sync_donation_accounting_state_for_payment_entry(self)

	def on_change(self):
		super_on_change = getattr(super(), "on_change", None)
		if callable(super_on_change):
			super_on_change()
		if self.docstatus == 1:
			sync_donation_reconciliation_state_for_payment_entry(self)

	def get_valid_reference_doctypes(self):
		# Donor payments may only reference Donations. Every other party type
		# (including the custom "Member" party type registered by this app)
		# keeps stock behaviour: ERPNext skips reference-doctype validation
		# when this returns None.
		if self.party_type == "Donor":
			return ("Donation",)
		return super().get_valid_reference_doctypes()

	def set_missing_ref_details(
		self,
		force: bool = False,
		update_ref_details_only_for: list | None = None,
		reference_exchange_details: dict | None = None,
	) -> None:
		# Mirrors PaymentEntry.set_missing_ref_details, except reference
		# details are fetched via get_payment_reference_details() so Donation
		# references get their amounts from the Donation document.
		for d in self.get("references"):
			if not d.allocated_amount:
				continue

			if (
				update_ref_details_only_for
				and (d.reference_doctype, d.reference_name) not in update_ref_details_only_for
			):
				continue

			ref_details = get_payment_reference_details(
				d.reference_doctype,
				d.reference_name,
				self.party_account_currency,
				self.party_type,
				self.party,
			)

			# Only update exchange rate when the reference is Journal Entry
			if (
				reference_exchange_details
				and d.reference_doctype == reference_exchange_details.reference_doctype
				and d.reference_name == reference_exchange_details.reference_name
			):
				ref_details.update({"exchange_rate": reference_exchange_details.exchange_rate})

			for field, value in ref_details.items():
				if d.exchange_gain_loss:
					# for cases where gain/loss is booked into invoice
					# exchange_gain_loss is calculated from invoice & populated
					# and row.exchange_rate is already set to payment entry's exchange rate
					# refer -> `update_reference_in_payment_entry()` in utils.py
					continue

				if field == "exchange_rate" or not d.get(field) or force:
					if self.get("_action") in ("submit", "cancel"):
						d.db_set(field, value)
					else:
						d.set(field, value)


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

	doc = frappe.get_doc(dt, dn)

	party_account = get_party_account("Donor", doc.get("donor"), doc.company)
	party_account_currency = doc.get("party_account_currency") or get_account_currency(party_account)
	grand_total = outstanding_amount = flt(party_amount) or flt(doc.amount)

	# bank or cash
	bank = get_bank_cash_account(doc, bank_account)

	paid_amount = abs(outstanding_amount)
	if party_account_currency == bank.account_currency:
		received_amount = paid_amount
	else:
		received_amount = flt(bank_amount) or paid_amount * flt(doc.get("conversion_rate", 1))

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive"
	pe.company = doc.company
	pe.cost_center = doc.get("cost_center")
	pe.project = doc.get("project")
	pe.posting_date = getdate()
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
			"allocated_amount": outstanding_amount,
		},
	)

	pe.setup_party_account_field()
	pe.set_missing_values()

	if party_account and bank:
		pe.set_exchange_rate()
		pe.set_amounts()

	return pe


def sync_donation_accounting_state_for_payment_entry(payment_entry) -> None:
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


def _submitted_donation_payment_total(donation_name: str) -> float:
	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_reference = frappe.qb.DocType("Payment Entry Reference")
	total = (
		frappe.qb.from_(payment_reference)
		.inner_join(payment_entry)
		.on(payment_entry.name == payment_reference.parent)
		.select(Sum(payment_reference.allocated_amount))
		.where(payment_entry.docstatus == 1)
		.where(payment_reference.reference_doctype == "Donation")
		.where(payment_reference.reference_name == donation_name)
	).run()[0][0]
	return flt(total)


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
			"outstanding_amount": amount,
			"exchange_rate": 1,
			"bill_no": None,
		}
	)
