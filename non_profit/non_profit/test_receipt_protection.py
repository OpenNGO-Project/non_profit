"""Tests for password-protected Spendenbescheinigung delivery."""

import shutil
from unittest import skipUnless
from unittest.mock import patch

import frappe

from non_profit.non_profit import tax_receipts
from non_profit.non_profit.receipt_protection import receipt_password, receipt_protection_enabled
from non_profit.non_profit.test_tax_receipts import TaxReceiptFixtures

# frappe's `get_pdf` shells out to wkhtmltopdf through pdfkit. The bench image
# ships the binary, so this passes locally; the CI runner installs only
# mariadb-client, where pdfkit raises `FileNotFoundError: b''` before any
# encryption happens. Guard rather than install it in CI: the assertion is about
# our wiring reaching frappe's encryption, not about PDF rendering itself.
WKHTMLTOPDF_AVAILABLE = bool(shutil.which("wkhtmltopdf"))


class ReceiptProtectionFixtures(TaxReceiptFixtures):
	def _set_protection(self, enabled: bool, source: str = "Postal Code") -> None:
		settings = frappe.get_single("Non Profit Settings")
		settings.protect_receipt_pdf = 1 if enabled else 0
		settings.receipt_pdf_password_source = source
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)


class TestReceiptPassword(ReceiptProtectionFixtures):
	def test_protection_is_off_by_default_for_this_suite(self):
		self._set_protection(False)
		self.assertFalse(receipt_protection_enabled())

	def test_no_password_when_protection_is_off(self):
		self._set_protection(False)
		donor, _contact = self._contact_donor("Ohne Schutz", email=f"ohne.{self.suffix}@example.com")
		self.assertIsNone(receipt_password(donor.name))

	def test_postal_code_source_uses_the_donor_postal_code(self):
		self._set_protection(True, "Postal Code")
		donor, _contact = self._contact_donor("Mit Plz", email=f"plz.{self.suffix}@example.com")
		# TaxReceiptFixtures._address seeds pincode 8000 on the contact address.
		self.assertEqual(receipt_password(donor.name), "8000")

	def test_donor_id_source_uses_the_donor_name(self):
		self._set_protection(True, "Donor ID")
		donor, _contact = self._contact_donor("Mit Id", email=f"id.{self.suffix}@example.com")
		self.assertEqual(receipt_password(donor.name), donor.name)

	def test_missing_postal_code_refuses_rather_than_sending_unprotected(self):
		self._set_protection(True, "Postal Code")
		donor = self._subjectless_donor()
		with self.assertRaises(frappe.ValidationError):
			receipt_password(donor.name)


class TestReceiptEmailPassesPassword(ReceiptProtectionFixtures):
	def _receipt_for(self, donor: str) -> str:
		self._donation(donor, 120, f"{self.tax_year}-05-01")
		tax_receipts.generate_receipts(self.company, self.tax_year)
		return frappe.db.get_value(
			"Donation Tax Receipt", {"donor": donor, "tax_year": self.tax_year}, "name"
		)

	def _send_and_capture_attach_print(self, receipt: str):
		with (
			patch.object(
				frappe, "attach_print", return_value={"fname": "r.pdf", "fcontent": b"%PDF-1.4"}
			) as attach_print,
			patch.object(tax_receipts, "send_referenced_email"),
		):
			tax_receipts.send_receipt_email(receipt)
		return attach_print

	def test_password_is_passed_to_attach_print_when_enabled(self):
		self._set_protection(True, "Postal Code")
		donor, _contact = self._contact_donor("Geschuetzt", email=f"geschuetzt.{self.suffix}@example.com")
		attach_print = self._send_and_capture_attach_print(self._receipt_for(donor.name))
		self.assertEqual(attach_print.call_args.kwargs["password"], "8000")

	def test_no_password_is_passed_when_disabled(self):
		self._set_protection(False)
		donor, _contact = self._contact_donor("Offen", email=f"offen.{self.suffix}@example.com")
		attach_print = self._send_and_capture_attach_print(self._receipt_for(donor.name))
		self.assertIsNone(attach_print.call_args.kwargs["password"])


class TestPdfIsActuallyEncrypted(ReceiptProtectionFixtures):
	@skipUnless(WKHTMLTOPDF_AVAILABLE, "wkhtmltopdf is not installed")
	def test_frappe_get_pdf_produces_a_password_protected_file(self):
		"""The encryption itself is frappe's; this proves the wiring reaches it."""
		from io import BytesIO

		from frappe.utils.pdf import get_pdf
		from pypdf import PdfReader

		pdf = get_pdf("<p>Spendenbescheinigung</p>", options={"password": "8000"})
		reader = PdfReader(BytesIO(pdf))

		self.assertTrue(reader.is_encrypted)
		self.assertTrue(reader.decrypt("8000"))
