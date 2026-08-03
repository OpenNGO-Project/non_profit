from decimal import Decimal
from importlib.util import find_spec
from unittest import skipUnless
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

GOOD_CONNECTOR_AVAILABLE = find_spec("good_connector") is not None
LEGACY_QRR = "000000000000000002026000014"
DONATION_QRR = "020000000000000002026000018"
SALES_INVOICE_QRR = "010000000000000002026001604"


def _good_connector_qrr_registration_available() -> bool:
	if not GOOD_CONNECTOR_AVAILABLE:
		return False
	from good_connector import qr_bill

	return all(
		callable(getattr(qr_bill, name, None))
		for name in ("assert_unique_qrr_reference", "is_qr_iban", "resolve_qrr_reference")
	)


GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE = _good_connector_qrr_registration_available()


class TestDonationEbicsProvider(UnitTestCase):
	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_backfill_sets_qrr_on_existing_submitted_donations(self):
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch("non_profit.non_profit.bank_integration.frappe.db.exists", return_value=True),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_all",
				return_value=[frappe._dict(name="DON-1", company="Test Company")],
			) as get_all,
			patch("good_connector.qr_bill.resolve_qrr_reference", return_value=DONATION_QRR),
			patch("good_connector.qr_bill.assert_unique_qrr_reference"),
			patch("non_profit.non_profit.bank_integration.frappe.db.set_value") as set_value,
		):
			backfill_donation_qr_references()
		get_all.assert_called_once_with(
			"Donation",
			filters={"docstatus": 1, "gc_qr_reference": ["is", "not set"]},
			fields=["name", "company"],
			limit_page_length=0,
		)
		set_value.assert_called_once_with(
			"Donation",
			{"name": "DON-1", "gc_qr_reference": ["is", "not set"]},
			"gc_qr_reference",
			DONATION_QRR,
			update_modified=False,
		)

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_backfill_preserves_populated_legacy_qrr(self):
		references = {"DON-LEGACY": None, "DON-MISSING": None}

		def resolve_reference(name, *, doctype):
			self.assertEqual(doctype, "Donation")
			if name == "DON-LEGACY":
				# Model registration populating the row after the backfill read.
				references[name] = LEGACY_QRR
			return DONATION_QRR

		def set_value(_doctype, filters, _fieldname, value, *, update_modified):
			self.assertFalse(update_modified)
			self.assertEqual(filters["gc_qr_reference"], ["is", "not set"])
			name = filters["name"]
			if not references[name]:
				references[name] = value

		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch("non_profit.non_profit.bank_integration.frappe.db.exists", return_value=True),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_all",
				return_value=[
					frappe._dict(name="DON-LEGACY", company="Test Company"),
					frappe._dict(name="DON-MISSING", company="Test Company"),
				],
			),
			patch("good_connector.qr_bill.resolve_qrr_reference", side_effect=resolve_reference),
			patch("good_connector.qr_bill.assert_unique_qrr_reference"),
			patch(
				"non_profit.non_profit.bank_integration.frappe.db.set_value",
				side_effect=set_value,
			),
		):
			backfill_donation_qr_references()

		self.assertEqual(references["DON-LEGACY"], LEGACY_QRR)
		self.assertEqual(references["DON-MISSING"], DONATION_QRR)

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_qr_iban_slip_uses_shared_donation_reference(self) -> None:
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		captured = {}

		class FakeQRBill:
			def __init__(self, **kwargs):
				captured.update(kwargs)

			def as_svg(self, output):
				output.write("<svg/>")

		doc = frappe._dict(
			amount=50,
			doctype="Donation",
			name="DON-TEST-003",
			gc_qr_reference=LEGACY_QRR,
		)
		with (
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch(
				"non_profit.non_profit.swiss_qrbill._resolve_creditor",
				return_value=("CH4431999123000889012", {"name": "Test NGO"}),
			),
			patch("good_connector.qr_bill.is_qr_iban", return_value=True),
			patch.dict("sys.modules", {"qrbill": frappe._dict(QRBill=FakeQRBill)}),
		):
			result = swiss_qrbill_svg(doc)

		self.assertEqual(result, "<svg/>")
		self.assertEqual(captured["reference_number"], doc.gc_qr_reference)

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_sales_invoice_slip_uses_sales_invoice_namespace(self) -> None:
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		captured = {}

		class FakeQRBill:
			def __init__(self, **kwargs):
				captured.update(kwargs)

			def as_svg(self, output):
				output.write("<svg/>")

		doc = frappe._dict(doctype="Sales Invoice", grand_total=50, name="SINV-2026-00160")
		with (
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch(
				"non_profit.non_profit.swiss_qrbill._resolve_creditor",
				return_value=("CH4431999123000889012", {"name": "Test NGO"}),
			),
			patch("good_connector.qr_bill.is_qr_iban", return_value=True),
			patch(
				"good_connector.qr_bill.resolve_qrr_reference",
				return_value=SALES_INVOICE_QRR,
			) as resolve_reference,
			patch.dict("sys.modules", {"qrbill": frappe._dict(QRBill=FakeQRBill)}),
		):
			result = swiss_qrbill_svg(doc)

		self.assertEqual(result, "<svg/>")
		self.assertEqual(captured["reference_number"], SALES_INVOICE_QRR)
		resolve_reference.assert_called_once_with(
			doc.name,
			doctype="Sales Invoice",
			stored_reference=None,
		)

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_ordinary_iban_slip_does_not_emit_qrr(self) -> None:
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		captured = {}

		class FakeQRBill:
			def __init__(self, **kwargs):
				captured.update(kwargs)

			def as_svg(self, output):
				output.write("<svg/>")

		with (
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch(
				"non_profit.non_profit.swiss_qrbill._resolve_creditor",
				return_value=("CH9300762011623852957", {"name": "Test NGO"}),
			),
			patch("good_connector.qr_bill.is_qr_iban", return_value=False),
			patch.dict("sys.modules", {"qrbill": frappe._dict(QRBill=FakeQRBill)}),
		):
			result = swiss_qrbill_svg(frappe._dict(amount=50, name="DON-TEST-004"))

		self.assertEqual(result, "<svg/>")
		self.assertIsNone(captured["reference_number"])

	def test_uninstalled_good_connector_does_not_emit_qrr(self) -> None:
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		captured = {}

		class FakeQRBill:
			def __init__(self, **kwargs):
				captured.update(kwargs)

			def as_svg(self, output):
				output.write("<svg/>")

		with (
			# No SVG provider registered: the standalone fallback renders. A
			# document without a stored reference emits none — a stored
			# gc_qr_reference WOULD be emitted (payment identity, covered by
			# test_qr_iban_slip_uses_shared_donation_reference).
			patch("non_profit.non_profit.swiss_qrbill.frappe.get_hooks", return_value=[]),
			patch(
				"non_profit.non_profit.swiss_qrbill._resolve_creditor",
				return_value=("CH4431999123000889012", {"name": "Test NGO"}),
			),
			patch.dict("sys.modules", {"qrbill": frappe._dict(QRBill=FakeQRBill)}),
		):
			result = swiss_qrbill_svg(frappe._dict(amount=50, name="DON-TEST-005"))

		self.assertEqual(result, "<svg/>")
		self.assertIsNone(captured["reference_number"])

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_registration_persists_shared_qrr(self):
		donation = Mock()
		donation.docstatus = 1
		donation.name = "NPO-DTN-2026-00001"
		donation.company = "Test Company"
		donation.get.return_value = None
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"good_connector.qr_bill.resolve_qrr_reference", return_value=DONATION_QRR
			) as resolve_reference,
			patch("good_connector.qr_bill.assert_unique_qrr_reference") as assert_unique,
		):
			result = register_donation_qr_reference(donation)
		self.assertEqual(result, DONATION_QRR)
		resolve_reference.assert_called_once_with(
			donation.name,
			doctype="Donation",
			stored_reference=None,
		)
		assert_unique.assert_called_once_with(
			"Donation", donation.name, DONATION_QRR, company=donation.company
		)
		donation.db_set.assert_called_once_with("gc_qr_reference", DONATION_QRR, update_modified=False)

	@skipUnless(
		GOOD_CONNECTOR_QRR_REGISTRATION_AVAILABLE,
		"good_connector QRR registration contract is not available",
	)
	def test_registration_preserves_valid_stored_qrr(self):
		donation = Mock()
		donation.docstatus = 1
		donation.name = "NPO-DTN-2026-00001"
		donation.company = "Test Company"
		donation.get.return_value = LEGACY_QRR
		meta = Mock()
		meta.has_field.return_value = True
		with (
			patch(
				"non_profit.non_profit.bank_integration.frappe.get_installed_apps",
				return_value=["good_connector"],
			),
			patch("non_profit.non_profit.bank_integration.frappe.get_meta", return_value=meta),
			patch(
				"good_connector.qr_bill.resolve_qrr_reference",
				return_value=LEGACY_QRR,
			) as resolve_reference,
			patch("good_connector.qr_bill.assert_unique_qrr_reference"),
		):
			result = register_donation_qr_reference(donation)
		self.assertEqual(result, LEGACY_QRR)
		resolve_reference.assert_called_once_with(
			donation.name,
			doctype="Donation",
			stored_reference=LEGACY_QRR,
		)
		donation.db_set.assert_not_called()

	def test_uninstalled_good_connector_does_not_register_qrr(self):
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
