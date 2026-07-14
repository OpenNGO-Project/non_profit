# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest
from unittest.mock import patch

import erpnext
import frappe
from frappe.tests import IntegrationTestCase

from non_profit.non_profit.custom_doctype.payment_entry import (
	get_donation_payment_entry,
	get_payment_reference_details,
)
from non_profit.non_profit.doctype.donation.donation import create_gateway_donation
from non_profit.non_profit.doctype.donor.donor import (
	get_donor_email,
	get_or_create_customer_for_donor,
)


class TestDonation(unittest.TestCase):
	def setUp(self):
		company, receivable_account, cash_account = get_company_and_accounts()

		create_donor_type()
		settings = frappe.get_doc("Non Profit Settings")
		values = {
			"company": company,
			"donation_company": company,
			"default_donor_type": "_Test Donor",
			"automate_donation_payment_entries": 1,
			"donation_debit_account": receivable_account,
			"donation_payment_account": cash_account,
			"creation_user": "Administrator",
		}
		if any(settings.get(field) != value for field, value in values.items()):
			settings.update(values)
			settings.flags.ignore_permissions = True
			settings.save()

	def test_payment_entry_for_donations_marks_paid_and_clears_on_cancel(self):
		donation, payment_entry = create_donation_with_payment_entry()

		self.assertTrue(donation.name)

		self.assertEqual(donation.paid, 1)
		self.assertTrue(payment_entry.name)

		payment_entry.cancel()
		donation.reload()
		self.assertEqual(donation.paid, 0)

	def test_payment_entry_paid_flip_recomputes_donor_lifetime_total(self):
		donor = create_unique_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": get_active_fiscal_year_date(),
				"amount": 250,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		# Submitted but unpaid: no lifetime giving recorded yet.
		donor.reload()
		self.assertEqual(frappe.utils.flt(donor.total_lifetime_amount), 0)

		# Submitting a Payment Entry flips `paid` via db.set_value (fires no doc
		# hooks); the donor roll-up must still be recomputed off that flag.
		donation.create_payment_entry(date=get_active_fiscal_year_date())
		donation.reload()
		self.assertEqual(donation.paid, 1)

		donor.reload()
		self.assertEqual(frappe.utils.flt(donor.total_lifetime_amount), 250)
		self.assertEqual(donor.gift_count, 1)

	def test_payment_entry_clearance_marks_donation_reconciled(self):
		donation, payment_entry = create_donation_with_payment_entry()
		clearance_date = get_active_fiscal_year_date()

		payment_entry.db_set("clearance_date", clearance_date)

		donation.reload()
		self.assertEqual(donation.paid, 1)
		self.assertEqual(donation.reconciled, 1)
		self.assertEqual(donation.reconciled_on, clearance_date)
		self.assertEqual(donation.reconciled_payment_entry, payment_entry.name)

		payment_entry.db_set("clearance_date", None)

		donation.reload()
		self.assertEqual(donation.reconciled, 0)
		self.assertFalse(donation.reconciled_on)
		self.assertFalse(donation.reconciled_payment_entry)

	def test_bank_transaction_clearance_marks_donation_reconciled(self):
		donation, payment_entry = create_donation_with_payment_entry()
		clearance_date = get_active_fiscal_year_date()
		bank_transaction = frappe.new_doc("Bank Transaction")
		payment_row = frappe._dict(
			{
				"payment_document": "Payment Entry",
				"payment_entry": payment_entry.name,
			}
		)

		bank_transaction.clear_linked_payment_entry(payment_row, clearance_date=clearance_date)

		donation.reload()
		self.assertEqual(donation.reconciled, 1)
		self.assertEqual(donation.reconciled_on, clearance_date)
		self.assertEqual(donation.reconciled_payment_entry, payment_entry.name)

		bank_transaction.clear_linked_payment_entry(payment_row, clearance_date=None)

		donation.reload()
		self.assertEqual(donation.reconciled, 0)
		self.assertFalse(donation.reconciled_on)
		self.assertFalse(donation.reconciled_payment_entry)

	def test_payment_authorization_keeps_paid_state_when_payment_entry_fails(self):
		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": get_active_fiscal_year_date(),
				"amount": 25,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		with (
			patch.object(
				donation,
				"create_payment_entry",
				side_effect=RuntimeError("account mismatch"),
			),
			patch("frappe.log_error") as log_error,
		):
			self.assertRaises(RuntimeError, donation.on_payment_authorized, "Completed")

		donation.reload()
		self.assertEqual(donation.paid, 0)
		log_error.assert_called()

	def test_payment_entry_restores_account_permission_flag_on_failure(self):
		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": get_active_fiscal_year_date(),
				"amount": 25,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		original_flag = getattr(frappe.flags, "ignore_account_permission", False)
		frappe.flags.ignore_account_permission = False
		try:
			with patch(
				"non_profit.non_profit.custom_doctype.payment_entry.get_donation_payment_entry",
				side_effect=RuntimeError("boom"),
			):
				with self.assertRaises(RuntimeError):
					donation.create_payment_entry()
			self.assertFalse(frappe.flags.ignore_account_permission)
		finally:
			frappe.flags.ignore_account_permission = original_flag

	def test_send_thank_you_sets_audit_fields_without_receipt(self):
		template_name = f"_Test Donation Thank You {frappe.generate_hash(length=8)}"
		frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": template_name,
				"subject": "Danke {{ doc.name }}",
				"response": "<p>Danke {{ doc.donor_name }}</p>",
				"use_html": 1,
			}
		).insert(ignore_permissions=True)
		settings = frappe.get_doc("Non Profit Settings")
		settings.default_thank_you_template = template_name
		settings.flags.ignore_permissions = True
		settings.save()

		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": get_active_fiscal_year_date(),
				"amount": 25,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		with patch("frappe.sendmail", return_value=frappe._dict(name="EMAIL-Q-NPO")) as sendmail:
			self.assertTrue(donation.send_thank_you())

		donation.reload()
		self.assertEqual(donation.thank_you_sent, 1)
		self.assertEqual(donation.thank_you_email_queue, "EMAIL-Q-NPO")
		self.assertFalse(donation.receipt)
		sendmail.assert_called_once()
		self.assertEqual(sendmail.call_args.kwargs["reference_doctype"], "Donation")
		self.assertEqual(sendmail.call_args.kwargs["reference_name"], donation.name)

	def test_donation_slip_uses_python_generated_qr_context(self):
		from non_profit.non_profit.fundraising_setup import DONATION_SLIP_CH_HTML

		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": get_active_fiscal_year_date(),
				"amount": 25,
			}
		)

		with patch(
			"non_profit.non_profit.swiss_qrbill.swiss_qrbill_svg",
			return_value="<svg></svg>",
		):
			donation.before_print()

		self.assertEqual(donation.qr_bill_svg, "<svg></svg>")
		self.assertIn("doc.qr_bill_svg", DONATION_SLIP_CH_HTML)
		self.assertIn("donation-slip-qr-final-page-slip", DONATION_SLIP_CH_HTML)
		self.assertNotIn("swiss_qrbill_svg(doc)", DONATION_SLIP_CH_HTML)

	def test_yearly_receipts_include_thanked_donations_without_receipt(self):
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			generate_yearly_receipts,
		)

		donation_date = get_active_fiscal_year_date()
		fiscal_year = frappe.db.get_value(
			"Fiscal Year",
			{
				"year_start_date": ["<=", donation_date],
				"year_end_date": [">=", donation_date],
			},
			"name",
		)
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donor = create_unique_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": get_donor_email(donor),
				"date": donation_date,
				"amount": 33,
				"paid": 1,
				"thank_you_sent": 1,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		result = generate_yearly_receipts(fiscal_year)

		receipt_names = result.get("receipts", [])
		self.assertTrue(receipt_names)
		self.assertEqual(
			frappe.db.get_value("Donation Receipt", receipt_names[0], "country"),
			"Switzerland",
		)
		linked_donations = frappe.get_all(
			"Donation Receipt Item",
			filters={"parent": ["in", receipt_names]},
			pluck="donation",
		)
		donation.reload()
		self.assertIn(donation.name, linked_donations)
		self.assertFalse(donation.receipt)


class TestDonationPaymentEntryInvariants(IntegrationTestCase):
	def setUp(self):
		company, receivable_account, cash_account = get_company_and_accounts()
		create_donor_type()
		create_mode_of_payment(company)

		settings = frappe.get_doc("Non Profit Settings")
		values = {
			"company": company,
			"donation_company": company,
			"default_donor_type": "_Test Donor",
			"automate_donation_payment_entries": 1,
			"donation_debit_account": receivable_account,
			"donation_payment_account": cash_account,
			"creation_user": "Administrator",
		}
		if any(settings.get(field) != value for field, value in values.items()):
			settings.update(values)
			settings.flags.ignore_permissions = True
			settings.save()

	def test_second_allocation_uses_remaining_outstanding(self):
		donation = create_submitted_donation(100)
		first_payment = insert_donation_payment_entry(donation, party_amount=40)
		first_payment.submit()

		details = get_payment_reference_details(
			"Donation", donation.name, first_payment.paid_from_account_currency
		)
		self.assertEqual(frappe.utils.flt(details.total_amount), 100)
		self.assertEqual(frappe.utils.flt(details.outstanding_amount), 60)
		current_details = get_payment_reference_details(
			"Donation",
			donation.name,
			first_payment.paid_from_account_currency,
			current_payment_entry=first_payment.name,
		)
		self.assertEqual(frappe.utils.flt(current_details.outstanding_amount), 100)

		second_payment = get_donation_payment_entry("Donation", donation.name)
		self.assertEqual(frappe.utils.flt(second_payment.references[0].outstanding_amount), 60)
		self.assertEqual(frappe.utils.flt(second_payment.references[0].allocated_amount), 60)
		prepare_donation_payment_entry(second_payment)
		second_payment.insert()
		second_payment.submit()

		donation.reload()
		self.assertEqual(donation.paid, 1)

	def test_stale_draft_is_rejected_after_another_payment_submits(self):
		donation = create_submitted_donation(100)
		stale_payment = insert_donation_payment_entry(donation)
		winning_payment = insert_donation_payment_entry(donation)
		winning_payment.submit()

		with self.assertRaises(frappe.ValidationError):
			stale_payment.submit()

	def test_fully_allocated_donation_payment_helper_is_rejected(self):
		donation = create_submitted_donation(100)
		payment_entry = insert_donation_payment_entry(donation)
		payment_entry.submit()

		with self.assertRaisesRegex(frappe.ValidationError, "fully allocated"):
			get_donation_payment_entry("Donation", donation.name)

	def test_donation_company_mismatch_is_rejected(self):
		donation = create_submitted_donation(100)
		payment_entry = get_donation_payment_entry("Donation", donation.name)
		other_company = frappe.get_all(
			"Company",
			filters={
				"name": ["!=", donation.company],
				"default_receivable_account": ["is", "set"],
				"default_cash_account": ["is", "set"],
			},
			fields=["name", "default_receivable_account", "default_cash_account"],
			order_by="name",
			limit=1,
		)[0]
		payment_entry.company = other_company.name
		payment_entry.paid_from = other_company.default_receivable_account
		payment_entry.paid_to = other_company.default_cash_account
		payment_entry.paid_from_account_currency = frappe.db.get_value(
			"Account", payment_entry.paid_from, "account_currency"
		)
		payment_entry.paid_to_account_currency = frappe.db.get_value(
			"Account", payment_entry.paid_to, "account_currency"
		)
		prepare_donation_payment_entry(payment_entry)

		with self.assertRaisesRegex(frappe.ValidationError, "belongs to company"):
			payment_entry.insert()

	def test_wrong_donor_receivable_account_is_rejected(self):
		donation = create_submitted_donation(100)
		payment_entry = get_donation_payment_entry("Donation", donation.name)
		expected_account = payment_entry.paid_from
		wrong_account = get_alternate_receivable_account(donation.company, expected_account)
		payment_entry.paid_from = wrong_account
		payment_entry.paid_from_account_currency = frappe.db.get_value(
			"Account", wrong_account, "account_currency"
		)
		prepare_donation_payment_entry(payment_entry)

		with self.assertRaisesRegex(frappe.ValidationError, "requires Donor party account"):
			payment_entry.insert()

	def test_valid_single_allocation_and_cancellation(self):
		donation = create_submitted_donation(100)
		payment_entry = insert_donation_payment_entry(donation)
		payment_entry.submit()

		donation.reload()
		self.assertEqual(donation.paid, 1)

		payment_entry.cancel()
		donation.reload()
		self.assertEqual(donation.paid, 0)


def get_company_and_accounts():
	company_name = erpnext.get_default_company()
	company = frappe.get_doc("Company", company_name)
	return (
		company.name,
		company.default_receivable_account,
		company.default_cash_account,
	)


def get_active_fiscal_year_date():
	fiscal_year = frappe.get_all(
		"Fiscal Year",
		filters={"disabled": 0},
		fields=["year_start_date"],
		order_by="year_start_date desc",
		limit=1,
	)

	if fiscal_year:
		return fiscal_year[0].year_start_date

	return frappe.utils.getdate()


def create_donor_type():
	if not frappe.db.exists("Donor Type", "_Test Donor"):
		frappe.get_doc({"doctype": "Donor Type", "donor_type": "_Test Donor"}).insert()


def create_donor():
	donor = frappe.db.get_value("Donor", {"donor_name": "_Test Donor"}, "name", order_by="creation desc")
	if donor:
		donor_doc = frappe.get_doc("Donor", donor)
	else:
		donor_doc = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "_Test Donor",
				"donor_type": "_Test Donor",
			}
		).insert()
	get_or_create_customer_for_donor(donor_doc, email="donor@test.com")
	donor_doc.reload()
	return donor_doc


def create_donation_with_payment_entry(amount=100):
	donor = create_donor()
	create_mode_of_payment(frappe.get_cached_value("Non Profit Settings", None, "company"))
	payment = frappe._dict(
		{
			"amount": amount,
			"method": "Debit Card",
			"id": f"pay_{frappe.generate_hash(length=8)}",
		}
	)
	donation = create_gateway_donation(donor, payment)

	# This method is normally triggered from Payment Gateway handling. If
	# accounting details are missing, it should throw here rather than later.
	donation.create_payment_entry(date=get_active_fiscal_year_date())
	donation.reload()

	payment_entry = frappe.get_doc(
		"Payment Entry",
		frappe.db.get_value("Payment Entry", {"reference_no": donation.name}, "name"),
	)
	return donation, payment_entry


def create_unique_donor():
	donor_doc = frappe.get_doc(
		{
			"doctype": "Donor",
			"donor_name": f"_Test Donor {frappe.generate_hash(length=8)}",
			"donor_type": "_Test Donor",
		}
	).insert()
	get_or_create_customer_for_donor(
		donor_doc,
		email=f"donor-{frappe.generate_hash(length=8)}@test.com",
	)
	donor_doc.reload()
	return donor_doc


def create_submitted_donation(amount=100):
	donor = frappe.get_doc(
		{
			"doctype": "Donor",
			"donor_name": f"_Test Payment Donor {frappe.generate_hash(length=8)}",
			"donor_type": "_Test Donor",
		}
	).insert()
	company = frappe.get_cached_value("Non Profit Settings", None, "donation_company")
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"company": company,
			"donor": donor.name,
			"donor_name": donor.donor_name,
			"email": get_donor_email(donor),
			"date": get_active_fiscal_year_date(),
			"amount": amount,
			"mode_of_payment": "Debit Card",
		}
	).insert(ignore_permissions=True)
	donation.submit()
	return donation


def prepare_donation_payment_entry(payment_entry):
	payment_entry.reference_no = f"_Test Donation Payment {frappe.generate_hash(length=8)}"
	payment_entry.reference_date = get_active_fiscal_year_date()
	payment_entry.flags.ignore_mandatory = True
	return payment_entry


def insert_donation_payment_entry(donation, party_amount=None):
	payment_entry = get_donation_payment_entry("Donation", donation.name, party_amount=party_amount)
	prepare_donation_payment_entry(payment_entry)
	payment_entry.insert()
	return payment_entry


def get_alternate_receivable_account(company, expected_account):
	account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_type": "Receivable",
			"is_group": 0,
			"name": ["!=", expected_account],
		},
		"name",
	)
	if account:
		return account

	expected = frappe.get_doc("Account", expected_account)
	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"_Test Donation Receivable {frappe.generate_hash(length=6)}",
			"account_type": "Receivable",
			"account_currency": expected.account_currency,
			"company": company,
			"parent_account": expected.parent_account,
			"root_type": "Asset",
		}
	).insert()
	return account.name


def create_mode_of_payment(company):
	default_account = frappe.db.get_value("Company", company, "default_cash_account")
	account_row = {"company": company, "default_account": default_account}

	if not frappe.db.exists("Mode of Payment", "Debit Card"):
		frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": "Debit Card",
				"accounts": [account_row],
			}
		).insert()
		return

	mop = frappe.get_doc("Mode of Payment", "Debit Card")
	if any(row.company == company for row in mop.accounts):
		return

	mop.append("accounts", account_row)
	mop.save(ignore_permissions=True)
