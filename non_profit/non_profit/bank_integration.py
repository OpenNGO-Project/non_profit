from __future__ import annotations

from decimal import Decimal

import frappe
from erpnext.accounts.utils import get_account_currency
from frappe import _
from frappe.utils import flt


def register_donation_qr_reference(doc, method: str | None = None) -> str | None:
	del method
	if (
		"good_connector" not in frappe.get_installed_apps()
		or doc.docstatus == 2
		or not frappe.get_meta("Donation").has_field("gc_qr_reference")
	):
		return None
	from good_connector.qr_bill import assert_unique_qrr_reference, resolve_qrr_reference

	reference = resolve_qrr_reference(
		doc.name,
		doctype="Donation",
		stored_reference=doc.get("gc_qr_reference"),
	)
	assert_unique_qrr_reference("Donation", doc.name, reference, company=doc.company)
	if doc.get("gc_qr_reference") != reference:
		doc.db_set("gc_qr_reference", reference, update_modified=False)
	return reference


def backfill_donation_qr_references() -> None:
	if (
		"good_connector" not in frappe.get_installed_apps()
		or not frappe.db.exists("DocType", "Donation")
		or not frappe.get_meta("Donation").has_field("gc_qr_reference")
	):
		return
	from good_connector.qr_bill import assert_unique_qrr_reference, resolve_qrr_reference

	for donation in frappe.get_all(
		"Donation",
		filters={"docstatus": 1, "gc_qr_reference": ["is", "not set"]},
		fields=["name", "company"],
		limit_page_length=0,
	):
		reference = resolve_qrr_reference(donation.name, doctype="Donation")
		assert_unique_qrr_reference("Donation", donation.name, reference, company=donation.company)
		frappe.db.set_value(
			"Donation",
			{"name": donation.name, "gc_qr_reference": ["is", "not set"]},
			"gc_qr_reference",
			reference,
			update_modified=False,
		)


def _matching_donations(company: str, qr_reference: str) -> list[str]:
	donation = frappe.qb.DocType("Donation")
	return (
		frappe.qb.from_(donation)
		.select(donation.name)
		.where(donation.gc_qr_reference == qr_reference)
		.where(donation.company == company)
		.where(donation.docstatus == 1)
		.orderby(donation.name)
		.for_update()
	).run(pluck=True)


def _candidate(donation_name: str, *, eligible: bool = True) -> dict:
	candidate = {
		"reference_doctype": "Donation",
		"reference_name": donation_name,
		"eligible_for_automatic_reconciliation": eligible,
	}
	if eligible:
		candidate["payment_entry_builder"] = (
			"non_profit.non_profit.bank_integration.build_ebics_payment_entry"
		)
	return candidate


def _supports_automatic_currency_matching(
	donation_name: str, bank_transaction, bank_account: str | None = None
) -> bool:
	company_currency = frappe.get_cached_value("Company", bank_transaction.company, "default_currency")
	if company_currency != bank_transaction.currency:
		return False

	bank_account = bank_account or frappe.get_cached_value(
		"Bank Account", bank_transaction.bank_account, "account"
	)
	if not bank_account or get_account_currency(bank_account) != bank_transaction.currency:
		return False

	from non_profit.non_profit.custom_doctype.payment_entry import expected_donation_party_account

	donation = frappe.db.get_value("Donation", donation_name, ["company", "donor"], as_dict=True)
	if not donation or donation.company != bank_transaction.company:
		return False
	party_account = expected_donation_party_account(
		frappe._dict(company=donation.company, donor=donation.donor)
	)
	return bool(party_account and get_account_currency(party_account) == bank_transaction.currency)


def get_ebics_reconciliation_candidates(
	*, bank_transaction, qr_reference: str, amount: Decimal
) -> list[dict]:
	"""Return side-effect-free Donation candidates for one QRR."""
	donation_names = _matching_donations(bank_transaction.company, qr_reference)
	company_currency = frappe.get_cached_value("Company", bank_transaction.company, "default_currency")
	if company_currency != bank_transaction.currency:
		return [_candidate(donation_name, eligible=False) for donation_name in donation_names]
	if len(donation_names) != 1:
		# Preserve every identity collision for Good Connector's aggregate
		# candidate-count check; amount eligibility must never pick a winner.
		return [_candidate(donation_name) for donation_name in donation_names]
	donation_name = donation_names[0]
	if not _supports_automatic_currency_matching(donation_name, bank_transaction):
		return [_candidate(donation_name, eligible=False)]

	from non_profit.non_profit.custom_doctype.payment_entry import _donation_outstanding_amount

	if amount > Decimal(str(_donation_outstanding_amount(donation_name))).quantize(Decimal("0.01")):
		return [_candidate(donation_name, eligible=False)]
	return [_candidate(donation_name)]


def build_ebics_payment_entry(*, bank_transaction, candidate: dict, amount: Decimal, bank_account: str):
	if not _supports_automatic_currency_matching(candidate["reference_name"], bank_transaction, bank_account):
		frappe.throw(_("Donation automatic bank matching requires company-currency party and bank accounts."))
	from non_profit.non_profit.custom_doctype.payment_entry import build_donation_payment_entry

	return build_donation_payment_entry(
		dt="Donation",
		dn=candidate["reference_name"],
		party_amount=flt(amount),
		bank_account=bank_account,
		bank_amount=flt(amount),
		posting_date=bank_transaction.date,
	)
