from decimal import Decimal
from unittest.mock import Mock, patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.bank_integration import (
	_supports_automatic_currency_matching,
	backfill_donation_qr_references,
	build_ebics_payment_entry,
	get_ebics_reconciliation_candidates,
	register_donation_qr_reference,
)
from non_profit.non_profit.fundraising_setup import ensure_good_connector_bank_integration

LEGACY_QRR = "000000000000000002026000014"
DONATION_QRR = "020000000000000002026000018"


class TestDonationEbicsProvider(UnitTestCase):
	def test_backfill_dispatches_registered_provider(self):
		provider = Mock()
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch("non_profit.non_profit.bank_integration.frappe.db.exists", return_value=True),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"non_profit.non_profit.integration_hooks.first_provider",
				return_value=provider,
			),
		):
			backfill_donation_qr_references()
		provider.assert_called_once_with(doctype="Donation", filters={"docstatus": 1})

	def test_backfill_without_provider_is_noop(self):
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch("non_profit.non_profit.bank_integration.frappe.db.exists", return_value=True),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"non_profit.non_profit.integration_hooks.first_provider",
				return_value=None,
			),
		):
			backfill_donation_qr_references()

	def test_registration_dispatches_registered_provider(self):
		donation = Mock()
		donation.docstatus = 1
		provider = Mock(return_value=DONATION_QRR)
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"non_profit.non_profit.integration_hooks.first_provider",
				return_value=provider,
			),
		):
			result = register_donation_qr_reference(donation)
		self.assertEqual(result, DONATION_QRR)
		provider.assert_called_once_with(doc=donation, doctype="Donation")

	def test_no_provider_does_not_register_qrr(self):
		donation = Mock(docstatus=1, name="NPO-DTN-2026-00001")
		# No registration provider on the seam = the same no-op the old
		# installed-apps guard produced.
		with patch("non_profit.non_profit.integration_hooks.frappe.get_hooks", return_value=[]):
			self.assertIsNone(register_donation_qr_reference(donation))
		donation.db_set.assert_not_called()

	def test_uninstalled_good_connector_setup_is_noop(self):
		with (
			patch("non_profit.non_profit.fundraising_setup.frappe.get_hooks", return_value=[]),
			patch("non_profit.non_profit.integration_hooks.frappe.get_hooks", return_value=[]),
		):
			ensure_good_connector_bank_integration()

	def test_duplicate_qrr_identities_are_not_filtered_by_amount(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="CHF", bank_account="Test Bank Account"
		)
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_cached_value", return_value="CHF"),
			patch(
				"non_profit.non_profit.bank_integration._matching_donations", return_value=["DON-1", "DON-2"]
			),
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching"
			) as currencies,
		):
			candidates = get_ebics_reconciliation_candidates(
				bank_transaction=bank_transaction,
				qr_reference=LEGACY_QRR,
				amount=Decimal("42.50"),
			)
		self.assertEqual([candidate["reference_name"] for candidate in candidates], ["DON-1", "DON-2"])
		currencies.assert_not_called()

	def test_single_overpayment_is_ineligible_candidate(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="CHF", bank_account="Test Bank Account"
		)
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_cached_value", return_value="CHF"),
			patch("non_profit.non_profit.bank_integration._matching_donations", return_value=["DON-1"]),
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching",
				return_value=True,
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry._donation_outstanding_amount",
				return_value=20,
			),
		):
			candidates = get_ebics_reconciliation_candidates(
				bank_transaction=bank_transaction,
				qr_reference=LEGACY_QRR,
				amount=Decimal("42.50"),
			)
		self.assertEqual(candidates[0]["reference_name"], "DON-1")
		self.assertFalse(candidates[0]["eligible_for_automatic_reconciliation"])
		self.assertNotIn("payment_entry_builder", candidates[0])

	def test_single_supported_donation_is_candidate(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="CHF", bank_account="Test Bank Account"
		)
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_cached_value", return_value="CHF"),
			patch("non_profit.non_profit.bank_integration._matching_donations", return_value=["DON-1"]),
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching",
				return_value=True,
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry._donation_outstanding_amount",
				return_value=100,
			),
		):
			candidates = get_ebics_reconciliation_candidates(
				bank_transaction=bank_transaction,
				qr_reference=LEGACY_QRR,
				amount=Decimal("42.50"),
			)
		self.assertEqual([candidate["reference_name"] for candidate in candidates], ["DON-1"])

	def test_transaction_currency_mismatch_preserves_exact_identity(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="EUR", bank_account="Test Bank Account"
		)
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_cached_value", return_value="CHF"),
			patch(
				"non_profit.non_profit.bank_integration._matching_donations", return_value=["DON-1"]
			) as matching_donations,
		):
			candidates = get_ebics_reconciliation_candidates(
				bank_transaction=bank_transaction,
				qr_reference=LEGACY_QRR,
				amount=Decimal("42.50"),
			)
		self.assertEqual(candidates[0]["reference_name"], "DON-1")
		self.assertFalse(candidates[0]["eligible_for_automatic_reconciliation"])
		self.assertNotIn("payment_entry_builder", candidates[0])
		matching_donations.assert_called_once()

	def test_single_foreign_currency_donation_is_ineligible_candidate(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="CHF", bank_account="Test Bank Account"
		)
		with (
			patch("non_profit.non_profit.bank_integration.frappe.get_cached_value", return_value="CHF"),
			patch("non_profit.non_profit.bank_integration._matching_donations", return_value=["DON-1"]),
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching",
				return_value=False,
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry._donation_outstanding_amount"
			) as outstanding,
		):
			candidates = get_ebics_reconciliation_candidates(
				bank_transaction=bank_transaction,
				qr_reference=LEGACY_QRR,
				amount=Decimal("42.50"),
			)
		self.assertEqual(candidates[0]["reference_name"], "DON-1")
		self.assertFalse(candidates[0]["eligible_for_automatic_reconciliation"])
		self.assertNotIn("payment_entry_builder", candidates[0])
		outstanding.assert_not_called()

	def test_currency_check_rejects_foreign_donor_receivable_account(self):
		bank_transaction = frappe._dict(
			company="Test Company", currency="CHF", bank_account="Test Bank Account"
		)

		def cached_value(doctype, _name, _fieldname):
			return "CHF" if doctype == "Company" else "Bank - T"

		with (
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_cached_value",
				side_effect=cached_value,
			),
			patch(
				"non_profit.non_profit.bank_integration.frappe.db.get_value",
				return_value=frappe._dict(company="Test Company", donor="DONOR-1"),
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry.expected_donation_party_account",
				return_value="Receivable EUR - T",
			),
			patch(
				"non_profit.non_profit.bank_integration.get_account_currency",
				side_effect=lambda account: "EUR" if account == "Receivable EUR - T" else "CHF",
			),
		):
			self.assertFalse(_supports_automatic_currency_matching("DON-1", bank_transaction))

	def test_builder_uses_trusted_donation_payment_helper(self):
		candidate = {"reference_name": "DON-1"}
		bank_transaction = frappe._dict(date="2026-07-21")
		with (
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching",
				return_value=True,
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry.build_donation_payment_entry"
			) as build_payment_entry,
		):
			build_ebics_payment_entry(
				bank_transaction=bank_transaction,
				candidate=candidate,
				amount=Decimal("42.50"),
				bank_account="Bank - T",
			)
		build_payment_entry.assert_called_once_with(
			dt="Donation",
			dn="DON-1",
			party_amount=42.5,
			bank_account="Bank - T",
			bank_amount=42.5,
			posting_date=bank_transaction.date,
		)

	def test_builder_rejects_unsupported_currency_before_building(self):
		with (
			patch(
				"non_profit.non_profit.bank_integration._supports_automatic_currency_matching",
				return_value=False,
			),
			patch(
				"non_profit.non_profit.custom_doctype.payment_entry.build_donation_payment_entry"
			) as build_payment_entry,
			self.assertRaises(frappe.ValidationError),
		):
			build_ebics_payment_entry(
				bank_transaction=frappe._dict(date="2026-07-21"),
				candidate={"reference_name": "DON-1"},
				amount=Decimal("42.50"),
				bank_account="Bank - T",
			)
		build_payment_entry.assert_not_called()
