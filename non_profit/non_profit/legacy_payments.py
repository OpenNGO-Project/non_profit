from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form, getdate

from non_profit.non_profit.doctype.donor.donor import (
	find_donor_by_email,
	get_donor_email,
	get_or_create_customer_for_donor,
)

SENSITIVE_DONOR_NOTE_KEYS = ("pan", "tax_id", "tax id", "tax-number", "tax_number")


def log_legacy_payment_usage(dotted_path: str, document_name: str | None = None) -> None:
	frappe.logger("non_profit.compatibility").warning(
		"Deprecated Non Profit payment API used: %s document=%s",
		dotted_path,
		document_name or "",
	)


def create_gateway_donation(donor, payment):
	if not frappe.db.exists("Mode of Payment", payment.method):
		create_gateway_mode_of_payment(payment.method)
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"company": get_company_for_donations(),
			"donor": donor.name,
			"donor_name": donor.donor_name,
			"email": get_donor_email(donor),
			"date": getdate(),
			"amount": flt(payment.amount),
			"mode_of_payment": payment.method,
			"payment_id": payment.id,
		}
	).insert(ignore_mandatory=True)
	donation.submit()
	return donation


def get_gateway_donor(email):
	donor = find_donor_by_email(email)
	return frappe.get_doc("Donor", donor) if donor else None


def create_gateway_donor(payment: dict) -> str:
	donor_details = frappe._dict(payment)
	donor = frappe.new_doc("Donor")
	donor.update(
		{
			"donor_name": donor_details.email,
			"donor_type": frappe.db.get_single_value("Non Profit Settings", "default_donor_type"),
			"contact": donor_details.contact,
		}
	)
	if donor_details.get("notes"):
		donor = get_additional_gateway_notes(donor, donor_details)
	donor.insert(ignore_mandatory=True)
	get_or_create_customer_for_donor(donor, email=donor_details.email)
	return donor.name


def get_company_for_donations():
	company = frappe.db.get_single_value("Non Profit Settings", "donation_company")
	if not company:
		from non_profit.non_profit.utils import get_company

		company = get_company()
	return company


def get_additional_gateway_notes(donor, donor_details):
	if isinstance(donor_details.notes, dict):
		note_lines = []
		for key, value in donor_details.notes.items():
			if "name" in key.lower():
				donor.update({"donor_name": donor_details.notes.get(key)})
			if not is_sensitive_gateway_note_key(key):
				note_lines.append(f"{key}: {value}")
		if note_lines:
			donor.add_comment("Comment", "\n".join(note_lines))
	elif isinstance(donor_details.notes, str) and (notes := safe_gateway_note_text(donor_details.notes)):
		donor.add_comment("Comment", notes)
	return donor


def is_sensitive_gateway_note_key(key: object) -> bool:
	key = str(key or "").strip().lower()
	return any(part in key for part in SENSITIVE_DONOR_NOTE_KEYS)


def safe_gateway_note_text(notes: str) -> str:
	safe_lines = []
	for line in str(notes or "").splitlines():
		if not is_sensitive_gateway_note_key(line.split(":", 1)[0]):
			safe_lines.append(line)
	return "\n".join(safe_lines).strip()


def create_gateway_mode_of_payment(method):
	frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": method}).insert(ignore_mandatory=True)


def authorize_membership_payment(membership, status_changed_to: str | None = None) -> None:
	if status_changed_to not in ("Completed", "Authorized"):
		return
	membership.load_from_db()
	settings = frappe.get_doc("Non Profit Settings")
	if (
		membership.meta.has_field("invoice")
		and settings.allow_invoicing
		and settings.automate_membership_invoicing
	):
		generate_membership_invoice(
			membership,
			with_payment_entry=settings.automate_membership_payment_entries,
			save=True,
		)


def generate_membership_invoice(
	membership,
	*,
	save: bool = True,
	with_payment_entry: bool = False,
) -> Any:
	if not membership.meta.has_field("invoice"):
		frappe.throw(
			_(
				"Membership invoice generation is not available on this site. "
				"Use the Sales Invoice membership workflow instead."
			)
		)
	if not (membership.currency or membership.amount):
		frappe.throw(
			_("The payment for this membership is not paid. To generate invoice fill the payment details")
		)
	if membership.get("invoice"):
		frappe.throw(_("An invoice is already linked to this document"))

	member = frappe.get_doc("Member", membership.member)
	if not member.customer:
		frappe.throw(_("No customer linked to member {0}").format(frappe.bold(membership.member)))
	plan = frappe.get_doc("Membership Type", membership.membership_type)
	settings = frappe.get_doc("Non Profit Settings")
	validate_membership_invoice_settings(membership, plan, settings)

	invoice = make_membership_invoice(membership, member, plan, settings)
	membership.reload()
	membership.set("invoice", invoice.name)
	if with_payment_entry:
		make_membership_payment_entry(membership, settings, invoice)
	if save:
		membership.save()
	return invoice


def validate_membership_invoice_settings(membership, plan, settings) -> None:
	settings_link = get_link_to_form("Non Profit Settings", "Non Profit Settings")
	if not settings.membership_debit_account:
		frappe.throw(_("You need to set <b>Debit Account</b> in {0}").format(settings_link))
	if not settings.company:
		frappe.throw(_("You need to set <b>Default Company</b> for invoicing in {0}").format(settings_link))
	if not plan.linked_item:
		frappe.throw(
			_("Please set a Linked Item for the Membership Type {0}").format(
				get_link_to_form("Membership Type", membership.membership_type)
			)
		)


def make_membership_payment_entry(membership, settings, invoice) -> None:
	if not settings.membership_payment_account:
		frappe.throw(
			_("You need to set <b>Payment Account</b> for Membership in {0}").format(
				get_link_to_form("Non Profit Settings", "Non Profit Settings")
			)
		)
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	previous_ignore_account_permission = getattr(frappe.flags, "ignore_account_permission", False)
	frappe.flags.ignore_account_permission = True
	try:
		payment_entry = get_payment_entry(
			dt="Sales Invoice", dn=invoice.name, bank_amount=invoice.grand_total
		)
	finally:
		frappe.flags.ignore_account_permission = previous_ignore_account_permission
	payment_entry.paid_to = settings.membership_payment_account
	payment_entry.reference_no = membership.name
	payment_entry.reference_date = getdate()
	payment_entry.flags.ignore_mandatory = True
	payment_entry.save()
	payment_entry.submit()


def make_membership_invoice(membership, member, plan, settings):
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": member.customer,
			"debit_to": settings.membership_debit_account,
			"currency": membership.currency,
			"company": settings.company,
			"is_pos": 0,
			"items": [{"item_code": plan.linked_item, "rate": membership.amount, "qty": 1}],
		}
	)
	invoice.set_missing_values()
	invoice.insert()
	invoice.submit()
	frappe.msgprint(_("Sales Invoice created successfully"))
	return invoice
