# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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

	def test_payment_authorization_reverts_paid_state_when_payment_entry_fails(self):
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

	def test_payment_authorization_keeps_base_accounting_and_dispatch_order(self):
		donation = frappe.new_doc("Donation")
		donation.name = "NPO-DONATION-AUTHORIZATION-ORDER"
		donation.company = "_Test Non Profit Company"
		calls = []
		with (
			patch.object(donation, "db_set") as db_set,
			patch.object(donation, "load_from_db"),
			patch.object(donation, "create_payment_entry", side_effect=lambda: calls.append("accounting")),
			patch.object(
				donation,
				"_dispatch_payment_thank_you",
				side_effect=lambda: calls.append("thank_you"),
			),
			patch(
				"non_profit.non_profit.major_gifts.on_donation_change",
				side_effect=lambda _donation: calls.append("rollup"),
			),
		):
			donation.on_payment_authorized("Completed")

		self.assertEqual(calls, ["accounting", "thank_you", "rollup"])
		db_set.assert_called_once_with("paid", 1)

	def test_unsuccessful_payment_status_does_not_change_donation(self):
		donation = frappe.new_doc("Donation")
		with (
			patch.object(donation, "db_set") as db_set,
			patch.object(donation, "create_payment_entry") as create_payment_entry,
		):
			donation.on_payment_authorized("Failed")

		db_set.assert_not_called()
		create_payment_entry.assert_not_called()

	def test_legacy_mode_of_payment_facade_logs_and_preserves_none_return(self):
		from non_profit.non_profit.doctype.donation.donation import create_mode_of_payment

		with (
			patch("non_profit.non_profit.legacy_payments.create_gateway_mode_of_payment") as create,
			patch("non_profit.non_profit.legacy_payments.log_legacy_payment_usage") as log_usage,
		):
			result = create_mode_of_payment("Legacy Card")

		self.assertIsNone(result)
		create.assert_called_once_with("Legacy Card")
		log_usage.assert_called_once_with(
			"non_profit.non_profit.doctype.donation.donation.create_mode_of_payment"
		)

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
			DONATION_RECEIPT_NAMING_SERIES,
			_create_yearly_receipt_batch,
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

		fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
		with patch(
			"non_profit.non_profit.doctype.donation_receipt.donation_receipt._yearly_receipt_candidates",
			return_value=[frappe._dict(name=donation.name)],
		):
			result = _create_yearly_receipt_batch(
				fiscal_year=fiscal_year,
				period_from=str(fiscal_year_doc.year_start_date),
				period_to=str(fiscal_year_doc.year_end_date),
				country="Switzerland",
				language="de",
			)

		receipt_names = result.get("receipts", [])
		self.assertTrue(receipt_names)
		self.assertEqual(
			frappe.db.get_value("Donation Receipt", receipt_names[0], "naming_series"),
			DONATION_RECEIPT_NAMING_SERIES,
		)
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
		self._concurrency_global_state = _capture_concurrency_global_state()
		_configure_donation_payment_entry_test_settings()

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

	def test_submit_allocation_validation_uses_current_read_and_excludes_current_document(self):
		from non_profit.non_profit.custom_doctype.payment_entry import (
			_validate_donation_allocation_totals,
		)

		payment_entry = frappe._dict(
			name="NP-CURRENT-PE",
			references=[
				frappe._dict(
					reference_doctype="Donation",
					reference_name="NP-CURRENT-DONATION",
					allocated_amount=30,
				)
			],
		)
		states = {"NP-CURRENT-DONATION": frappe._dict(amount=100)}
		with patch(
			"non_profit.non_profit.custom_doctype.payment_entry._submitted_donation_payment_total",
			return_value=80,
		) as submitted_total:
			with self.assertRaisesRegex(frappe.ValidationError, "only 20"):
				_validate_donation_allocation_totals(payment_entry, states)

		submitted_total.assert_called_once_with(
			"NP-CURRENT-DONATION",
			"NP-CURRENT-PE",
			for_update=True,
		)

	def test_two_connections_allow_exactly_one_normal_full_allocation_submit(self):
		if frappe.db.db_type != "mariadb":
			self.skipTest("The REPEATABLE READ regression targets MariaDB/InnoDB")

		# This test must commit its fixture for the worker connections. Discard
		# uncommitted rows from earlier methods in this class before doing so.
		frappe.db.rollback()
		self._concurrency_global_state = _capture_concurrency_global_state()
		_configure_donation_payment_entry_test_settings()
		donation = create_submitted_donation(100)
		donor = donation.donor
		payment_entries = [insert_donation_payment_entry(donation).name for _index in range(2)]
		frappe.db.commit()
		try:
			barrier = Barrier(2)
			with ThreadPoolExecutor(max_workers=2) as executor:
				results = list(
					executor.map(
						_run_concurrent_allocation,
						[frappe.local.site, frappe.local.site],
						payment_entries,
						[donation.name, donation.name],
						[barrier, barrier],
					)
				)

			submitted_results = [result for result in results if result.endswith("submitted")]
			rejected_results = [result for result in results if result.endswith("rejected")]
			self.assertEqual(len(submitted_results), 1)
			self.assertEqual(len(rejected_results), 1)
			self.assertEqual(
				frappe.db.count("Payment Entry", {"name": ["in", payment_entries], "docstatus": 1}),
				1,
			)
			self.assertEqual(
				frappe.utils.flt(
					frappe.db.get_value(
						"Donation",
						donation.name,
						"advance_paid",
					)
				),
				100,
			)
		finally:
			frappe.db.rollback()
			_cleanup_concurrent_allocation_fixture(payment_entries, donation.name, donor)
			_restore_concurrency_global_state(self._concurrency_global_state)
			frappe.db.commit()

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


class TestDonationPaymentEntryHooks(IntegrationTestCase):
	"""Donation Payment Entry behaviour delivered through doc_events hooks.

	These run against whichever Payment Entry controller class is active
	(erpnext base or hrms on this bench): non_profit registers its Donation
	delta via doc_events plus the maintained Donation.grand_total /
	advance_paid mirrors, not via override_doctype_class.
	"""

	def setUp(self):
		_configure_donation_payment_entry_test_settings()

	def test_payment_entry_for_unpaid_donation_marks_paid(self):
		# The exact path that fails when ERPNext's generic reference-details
		# fallback cannot compute Donation outstanding amounts.
		donation = create_submitted_donation(125)
		self.assertEqual(frappe.utils.flt(donation.grand_total), 125)
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 0)
		self.assertEqual(donation.paid, 0)

		payment_entry = insert_donation_payment_entry(donation)
		payment_entry.submit()

		donation.reload()
		self.assertEqual(donation.paid, 1)
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 125)
		payment_entry.reload()
		self.assertEqual(frappe.utils.flt(payment_entry.references[0].total_amount), 125)
		self.assertEqual(frappe.utils.flt(payment_entry.references[0].outstanding_amount), 125)

	def test_advance_paid_and_grand_total_maintained_on_submit_and_cancel(self):
		donation = create_submitted_donation(100)

		first_payment = insert_donation_payment_entry(donation, party_amount=40)
		first_payment.submit()
		donation.reload()
		self.assertEqual(frappe.utils.flt(donation.grand_total), 100)
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 40)
		self.assertEqual(donation.paid, 0)

		second_payment = get_donation_payment_entry("Donation", donation.name)
		prepare_donation_payment_entry(second_payment)
		second_payment.insert()
		second_payment.submit()
		donation.reload()
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 100)
		self.assertEqual(donation.paid, 1)

		second_payment.cancel()
		donation.reload()
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 40)
		self.assertEqual(donation.paid, 0)

		first_payment.cancel()
		donation.reload()
		self.assertEqual(frappe.utils.flt(donation.advance_paid), 0)
		self.assertEqual(frappe.utils.flt(donation.grand_total), 100)

	def test_second_allocation_beyond_outstanding_is_rejected(self):
		donation = create_submitted_donation(100)
		first_payment = insert_donation_payment_entry(donation, party_amount=40)
		first_payment.submit()

		payment_entry = get_donation_payment_entry("Donation", donation.name)
		# Each row stays within the refetched outstanding (60), so ERPNext's
		# per-row allocated check passes; only the cumulative H1 hook rejects
		# this over-allocation.
		payment_entry.append(
			"references",
			{
				"reference_doctype": "Donation",
				"reference_name": donation.name,
				"total_amount": 100,
				"outstanding_amount": 60,
				"allocated_amount": 40,
			},
		)
		payment_entry.paid_amount = 100
		payment_entry.received_amount = 100
		prepare_donation_payment_entry(payment_entry)
		# Core rejects duplicate references first. Bypass only that overlapping
		# guard here to exercise the independent cumulative-allocation hook.
		with patch.object(type(payment_entry), "validate_duplicate_entry", return_value=None):
			payment_entry.insert()
			with self.assertRaisesRegex(frappe.ValidationError, "remaining outstanding"):
				payment_entry.submit()

	def test_cross_company_payment_entry_is_rejected(self):
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

	def test_backfill_donation_payment_totals_patch(self):
		donation = create_submitted_donation(100)
		first_payment = insert_donation_payment_entry(donation, party_amount=40)
		first_payment.submit()

		# Simulate the pre-patch state where neither mirror field was populated.
		frappe.db.set_value(
			"Donation",
			donation.name,
			{"grand_total": 0, "advance_paid": 0},
			update_modified=False,
		)

		from non_profit.patches.backfill_donation_payment_totals import execute

		execute()

		grand_total, advance_paid = frappe.db.get_value(
			"Donation", donation.name, ["grand_total", "advance_paid"]
		)
		self.assertEqual(frappe.utils.flt(grand_total), 100)
		self.assertEqual(frappe.utils.flt(advance_paid), 40)


def _capture_concurrency_global_state() -> dict:
	settings_fields = (
		"company",
		"donation_company",
		"default_donor_type",
		"automate_donation_payment_entries",
		"donation_debit_account",
		"donation_payment_account",
		"creation_user",
	)
	mode_of_payment = None
	if frappe.db.exists("Mode of Payment", "Debit Card"):
		mode_of_payment = frappe.get_doc("Mode of Payment", "Debit Card").as_dict()
	return {
		"settings": {
			fieldname: frappe.db.get_single_value("Non Profit Settings", fieldname, cache=False)
			for fieldname in settings_fields
		},
		"donor_type_exists": bool(frappe.db.exists("Donor Type", "_Test Donor")),
		"mode_of_payment": mode_of_payment,
	}


def _configure_donation_payment_entry_test_settings() -> None:
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


def _restore_concurrency_global_state(state: dict) -> None:
	for fieldname, value in state["settings"].items():
		filters = {"doctype": "Non Profit Settings", "field": fieldname}
		if value is None:
			frappe.db.delete("Singles", filters)
		elif frappe.db.exists("Singles", filters):
			frappe.db.set_value("Singles", filters, "value", value, update_modified=False)
		else:
			single_value = frappe.qb.DocType("Singles")
			(
				frappe.qb.into(single_value)
				.columns(single_value.doctype, single_value.field, single_value.value)
				.insert("Non Profit Settings", fieldname, value)
			).run()

	frappe.clear_document_cache("Non Profit Settings", "Non Profit Settings")
	if not state["donor_type_exists"] and frappe.db.exists("Donor Type", "_Test Donor"):
		restored_donor_type = frappe.db.get_single_value(
			"Non Profit Settings", "default_donor_type", cache=False
		)
		if restored_donor_type != state["settings"]["default_donor_type"]:
			raise AssertionError("Non Profit Settings.default_donor_type was not restored")
		if restored_donor_type != "_Test Donor":
			# The two-connection test can leave core's local Single-value cache on
			# the test fixture. The persisted setting was verified above, so ignore
			# only that stale Single link while removing the fixture it created.
			frappe.delete_doc(
				"Donor Type",
				"_Test Donor",
				ignore_doctypes=["Non Profit Settings"],
			)

	stored_mode = state["mode_of_payment"]
	if not stored_mode:
		if frappe.db.exists("Mode of Payment", "Debit Card"):
			frappe.delete_doc("Mode of Payment", "Debit Card")
		return
	mode_of_payment = frappe.get_doc("Mode of Payment", "Debit Card")
	mode_of_payment.set("accounts", stored_mode.get("accounts") or [])
	mode_of_payment.save(ignore_permissions=True)


def _run_concurrent_allocation(
	site: str,
	payment_entry_name: str,
	donation_name: str,
	barrier: Barrier,
) -> str:
	from non_profit.non_profit.custom_doctype.payment_entry import (
		_submitted_donation_payment_total,
	)

	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		deadlocked = False
		last_deadlock = None
		for attempt in range(3):
			try:
				payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
				payment_entry.flags.ignore_mandatory = True
				# Establish the stale REPEATABLE READ snapshot that caused the original race.
				_submitted_donation_payment_total(donation_name)
				if attempt == 0:
					barrier.wait(timeout=30)
				payment_entry.submit()
				frappe.db.commit()
				return "retried_submitted" if deadlocked else "submitted"
			except frappe.QueryDeadlockError as error:
				# A request retry must restart the complete transaction, including
				# reloading the Payment Entry and rebuilding its locking reads.
				last_deadlock = error
				deadlocked = True
				frappe.db.rollback()
			except frappe.ValidationError:
				frappe.db.rollback()
				return "retried_rejected" if deadlocked else "rejected"
		if last_deadlock:
			raise last_deadlock
		raise AssertionError("Concurrent allocation retry ended without an outcome")
	finally:
		frappe.destroy()


def _cleanup_concurrent_payment_entries(payment_entries: list[str]) -> None:
	from erpnext.accounts.utils import _delete_accounting_ledger_entries, _delete_adv_pl_entries

	for payment_entry_name in payment_entries:
		if not frappe.db.exists("Payment Entry", payment_entry_name):
			continue
		payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
		if payment_entry.docstatus == 1:
			payment_entry.cancel()
		_delete_accounting_ledger_entries("Payment Entry", payment_entry_name)
		_delete_adv_pl_entries("Payment Entry", payment_entry_name)
		frappe.delete_doc("Payment Entry", payment_entry_name, delete_permanently=True)

	for ledger_doctype in ("GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry"):
		if frappe.db.count(
			ledger_doctype,
			{"voucher_type": "Payment Entry", "voucher_no": ["in", payment_entries]},
		):
			raise AssertionError(f"{ledger_doctype} rows leaked from concurrent Payment Entry fixtures")
	if any(frappe.db.exists("Payment Entry", name) for name in payment_entries):
		raise AssertionError("Concurrent Payment Entry fixtures were not deleted")


def _cleanup_concurrent_allocation_fixture(
	payment_entries: list[str],
	donation_name: str,
	donor_name: str,
) -> None:
	_cleanup_concurrent_payment_entries(payment_entries)
	if frappe.db.exists("Donation", donation_name):
		donation = frappe.get_doc("Donation", donation_name)
		if donation.docstatus == 1:
			donation.cancel()
		frappe.delete_doc("Donation", donation_name, delete_permanently=True)
	if frappe.db.exists("Donor", donor_name):
		frappe.delete_doc("Donor", donor_name, delete_permanently=True)
	if frappe.db.exists("Donation", donation_name) or frappe.db.exists("Donor", donor_name):
		raise AssertionError("Concurrent Donation fixtures were not deleted")


def get_company_and_accounts():
	company_name = erpnext.get_default_company()
	company = frappe.get_doc("Company", company_name)
	receivable_account = company.default_receivable_account or frappe.db.get_value(
		"Account",
		{"company": company.name, "account_type": "Receivable", "is_group": 0},
		"name",
		order_by="name",
	)
	cash_account = company.default_cash_account or frappe.db.get_value(
		"Account",
		{"company": company.name, "account_type": "Cash", "is_group": 0},
		"name",
		order_by="name",
	)
	return (
		company.name,
		receivable_account,
		cash_account,
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
	default_account = frappe.db.get_value("Company", company, "default_cash_account") or frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Cash", "is_group": 0},
		"name",
		order_by="name",
	)
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
