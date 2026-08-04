from __future__ import annotations

from importlib.util import find_spec
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt, getdate, nowdate

from non_profit.non_profit.doctype.donor.donor import get_or_create_donor_for_contact
from non_profit.non_profit.fundraising_setup import (
	DONATION_TAX_RECEIPT_PRINT_FORMAT,
	ensure_tax_receipt_print_format,
)
from non_profit.non_profit.tax_receipts import (
	cancel_receipt,
	create_receipt_campaign,
	direct_mail_audience_provider,
	direct_mail_candidate_rows,
	donation_table_html,
	generate_receipts,
	mark_receipts_issued,
	receipt_campaign_reference,
	send_receipt_email,
)

GOOD_DIRECT_MAIL_AVAILABLE = find_spec("good_direct_mail") is not None


class TaxReceiptFixtures(IntegrationTestCase):
	"""Shared factories for the Spendenbescheinigung suite."""

	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.company = self._company()
		self.tax_year = self._unused_tax_year()
		self._donor_type()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		super().tearDown()

	def _company(self) -> str:
		companies = frappe.get_all(
			"Company",
			filters={"default_currency": "CHF"},
			pluck="name",
			order_by="name asc",
			limit=1,
		)
		if companies:
			return companies[0]
		return self._company_with_currency("CHF")

	def _company_with_currency(self, currency: str) -> str:
		hash_value = frappe.generate_hash(length=6)
		return (
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": f"NPO Receipt {currency} {hash_value}",
					"abbr": f"R{hash_value[:4]}".upper(),
					"country": "Switzerland",
					"default_currency": currency,
					"create_chart_of_accounts_based_on": "Standard Template",
					"chart_of_accounts": "Standard",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _unused_tax_year(self) -> int:
		# Keep ten years of headroom because focused tests also exercise historical
		# and empty runs relative to the selected year.
		for tax_year in range(2099, 2009, -1):
			date_range = (f"{tax_year}-01-01", f"{tax_year}-12-31")
			if frappe.db.exists("Donation", {"company": self.company, "date": ["between", date_range]}):
				continue
			if frappe.db.exists(
				"Donation Tax Receipt",
				{"company": self.company, "tax_year": tax_year},
			):
				continue
			return tax_year
		raise AssertionError(f"No unused Donation Tax Receipt test year is available for {self.company}")

	def _donor_type(self) -> str:
		if not frappe.db.exists("Donor Type", "_Test Donor"):
			frappe.get_doc({"doctype": "Donor Type", "donor_type": "_Test Donor"}).insert(
				ignore_permissions=True
			)
		return "_Test Donor"

	def _contact_donor(self, first_name: str, *, email: str | None = None) -> Any:
		values: dict[str, Any] = {
			"doctype": "Contact",
			"first_name": first_name,
			"last_name": f"Receipt {self.suffix}",
			"npo_identity_kind": "Person",
		}
		if email:
			values["email_ids"] = [{"email_id": email, "is_primary": 1}]
		contact = frappe.get_doc(values).insert(ignore_permissions=True)
		self._address("Contact", contact.name, f"{first_name} {self.suffix}")
		donor = get_or_create_donor_for_contact(contact.name, donor_type="_Test Donor")
		return donor, contact

	def _subjectless_donor(self) -> Any:
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Anonymous {self.suffix}",
				"donor_type": "_Test Donor",
			}
		).insert(ignore_permissions=True)

	def _address(self, link_doctype: str, link_name: str, title: str) -> Any:
		return frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				"address_line1": "Teststrasse 1",
				"pincode": "8000",
				"city": "Zurich",
				"country": "Switzerland",
				"links": [{"link_doctype": link_doctype, "link_name": link_name}],
			}
		).insert(ignore_permissions=True)

	def _donation(
		self,
		donor: str,
		amount: float,
		date: str,
		*,
		company: str | None = None,
		submit: bool = True,
		paid: bool = True,
	) -> Any:
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": company or self.company,
				"donor": donor,
				"date": date,
				"amount": amount,
				"paid": paid,
			}
		).insert(ignore_permissions=True)
		if submit:
			donation.submit()
		return donation


class TestDonationTaxReceiptGeneration(TaxReceiptFixtures):
	def test_empty_generation_still_takes_existing_company_lock(self) -> None:
		from non_profit.non_profit import tax_receipts

		with patch.object(
			tax_receipts,
			"_lock_generation_scope",
			wraps=tax_receipts._lock_generation_scope,
		) as lock_scope:
			report = generate_receipts(self.company, self.tax_year - 10)
		lock_scope.assert_called_once_with(self.company)
		self.assertEqual(
			report,
			{"created": 0, "updated": 0, "deleted": 0, "unchanged": 0, "stale_issued": []},
		)

	def test_qualifying_rules_grouping_idempotence_and_stale_issued(self) -> None:
		donor_a, _contact_a = self._contact_donor("Anna")
		donor_b, _contact_b = self._contact_donor("Bruno")

		self._donation(donor_a.name, 100, f"{self.tax_year}-03-01")
		self._donation(donor_a.name, 150, f"{self.tax_year}-09-01")
		self._donation(donor_b.name, 75, f"{self.tax_year}-05-01")
		# Not qualifying: unpaid, draft, cancelled, and outside the tax year.
		self._donation(donor_a.name, 1000, f"{self.tax_year}-03-15", paid=False)
		self._donation(donor_a.name, 999, f"{self.tax_year}-04-01", submit=False)
		cancelled = self._donation(donor_a.name, 888, f"{self.tax_year}-04-02")
		cancelled.cancel()
		self._donation(donor_a.name, 777, f"{self.tax_year - 1}-06-15")

		report = generate_receipts(self.company, self.tax_year)
		self.assertEqual(report["created"], 2)
		self.assertEqual(report["updated"], 0)
		self.assertEqual(report["stale_issued"], [])

		receipt_a = self._receipt(donor_a.name)
		self.assertEqual(flt(receipt_a.total_amount), 250.0)
		self.assertEqual(receipt_a.donation_count, 2)
		self.assertEqual(receipt_a.status, "Draft")
		self.assertEqual(receipt_a.currency, "CHF")
		self.assertTrue(receipt_a.name.startswith(f"NPO-STR-{self.tax_year}-"))
		details = frappe.parse_json(receipt_a.donation_details)
		self.assertEqual([row["amount"] for row in details], [100.0, 150.0])

		receipt_b = self._receipt(donor_b.name)
		self.assertEqual(flt(receipt_b.total_amount), 75.0)

		# Re-running without changes must not touch anything.
		rerun = generate_receipts(self.company, self.tax_year)
		self.assertEqual(
			rerun,
			{"created": 0, "updated": 0, "deleted": 0, "unchanged": 2, "stale_issued": []},
		)

		# A new donation refreshes the still-Draft receipt.
		self._donation(donor_a.name, 50, f"{self.tax_year}-11-01")
		updated = generate_receipts(self.company, self.tax_year)
		self.assertEqual(updated["updated"], 1)
		self.assertEqual(updated["unchanged"], 1)
		self.assertEqual(flt(self._receipt(donor_a.name).total_amount), 300.0)

		# Once issued, a late donation is reported, never silently applied.
		issued = mark_receipts_issued(self.company, self.tax_year)
		self.assertEqual(issued, 2)
		receipt_a = self._receipt(donor_a.name)
		self.assertEqual(receipt_a.status, "Issued")
		self.assertEqual(receipt_a.issued_on, getdate(nowdate()))

		self._donation(donor_a.name, 25, f"{self.tax_year}-12-01")
		stale = generate_receipts(self.company, self.tax_year)
		self.assertEqual(stale["stale_issued"], [receipt_a.name])
		self.assertEqual(flt(self._receipt(donor_a.name).total_amount), 300.0)

	def test_direct_insert_and_generated_field_changes_require_service_capability(self) -> None:
		donor, _contact = self._contact_donor("Clara")
		self._donation(donor.name, 40, f"{self.tax_year}-02-01")
		generate_receipts(self.company, self.tax_year)

		with self.assertRaisesRegex(frappe.ValidationError, "only be created by the receipt service"):
			frappe.get_doc(
				{
					"doctype": "Donation Tax Receipt",
					"donor": donor.name,
					"tax_year": self.tax_year - 1,
					"company": self.company,
					"currency": "CHF",
					"status": "Draft",
				}
			).insert(ignore_permissions=True)

		receipt = self._receipt(donor.name)
		changes = {
			"donor": self._subjectless_donor().name,
			"tax_year": self.tax_year - 1,
			"company": self._company_with_currency("CHF"),
			"currency": "EUR",
			"status": "Issued",
			"issued_on": nowdate(),
			"total_amount": 999,
			"donation_count": 99,
			"donation_details": "[]",
		}
		for fieldname, value in changes.items():
			with self.subTest(fieldname=fieldname):
				receipt.reload()
				receipt.set(fieldname, value)
				with self.assertRaisesRegex(frappe.ValidationError, "Receipt service"):
					receipt.save()

		# A forged flag value must not pass the identity check either.
		receipt.reload()
		receipt.status = "Issued"
		receipt.flags.donation_tax_receipt_service_write = True
		with self.assertRaisesRegex(frappe.ValidationError, "Donation Tax Receipt service"):
			receipt.save()

		receipt.reload()
		receipt.language = "fr"
		receipt.remarks = "Operator note"
		receipt.save()
		self.assertEqual(receipt.language, "fr")

		receipt.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "only be deleted by the receipt service"):
			receipt.delete()

	def test_tax_year_company_currency_and_company_permission_are_validated(self) -> None:
		_donor, _contact = self._contact_donor("Dora")
		with self.assertRaisesRegex(frappe.ValidationError, "Tax Year must be between"):
			generate_receipts(self.company, 1899)

		eur_company = self._company_with_currency("EUR")
		with self.assertRaisesRegex(frappe.ValidationError, "Company with CHF"):
			generate_receipts(eur_company, self.tax_year)

		denied_company = self._company_with_currency("CHF")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"receipt-restricted-{self.suffix}@example.com",
				"first_name": "Receipt Restricted",
				"enabled": 1,
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": "System Manager"}, {"role": "Non Profit Manager"}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user.name,
				"allow": "Company",
				"for_value": self.company,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				generate_receipts(denied_company, self.tax_year)
		finally:
			frappe.set_user("Administrator")

	def test_autoname_uses_historical_tax_year_not_creation_year(self) -> None:
		donor, _contact = self._contact_donor("Erna")
		historical_year = self.tax_year - 3
		self._donation(donor.name, 35, f"{historical_year}-06-01")
		generate_receipts(self.company, historical_year)
		receipt = frappe.get_doc(
			"Donation Tax Receipt",
			{"donor": donor.name, "tax_year": historical_year, "company": self.company},
		)
		self.assertTrue(receipt.name.startswith(f"NPO-STR-{historical_year}-"))
		self.assertNotIn(f"NPO-STR-{self.tax_year}-", receipt.name)

	def test_stale_draft_is_deleted_and_stale_issued_without_group_is_reported(self) -> None:
		draft_donor, _contact = self._contact_donor("Draft Stale")
		draft_donation = self._donation(draft_donor.name, 60, f"{self.tax_year}-05-01")
		generate_receipts(self.company, self.tax_year)
		draft_receipt = self._receipt(draft_donor.name)
		frappe.db.set_value("Donation", draft_donation.name, "paid", 0, update_modified=False)
		report = generate_receipts(self.company, self.tax_year)
		self.assertEqual(report["deleted"], 1)
		self.assertFalse(frappe.db.exists("Donation Tax Receipt", draft_receipt.name))

		issued_donor, _contact = self._contact_donor("Issued Stale")
		issued_donation = self._donation(issued_donor.name, 70, f"{self.tax_year}-05-02")
		generate_receipts(self.company, self.tax_year)
		issued_receipt = self._receipt(issued_donor.name)
		self.assertEqual(
			mark_receipts_issued(self.company, self.tax_year, [issued_receipt.name]),
			1,
		)
		frappe.db.set_value("Donation", issued_donation.name, "paid", 0, update_modified=False)
		report = generate_receipts(self.company, self.tax_year)
		self.assertEqual(report["stale_issued"], [issued_receipt.name])
		self.assertTrue(frappe.db.exists("Donation Tax Receipt", issued_receipt.name))

	def test_mark_issued_defaults_to_postal_candidates_and_explicit_names_are_supported(self) -> None:
		addressable, _contact = self._contact_donor("Addressable")
		subjectless = self._subjectless_donor()
		self._donation(addressable.name, 45, f"{self.tax_year}-07-01")
		self._donation(subjectless.name, 55, f"{self.tax_year}-07-02")
		generate_receipts(self.company, self.tax_year)

		self.assertEqual(mark_receipts_issued(self.company, self.tax_year), 1)
		self.assertEqual(self._receipt(addressable.name).status, "Issued")
		subjectless_receipt = self._receipt(subjectless.name)
		self.assertEqual(subjectless_receipt.status, "Draft")
		self.assertEqual(
			mark_receipts_issued(self.company, self.tax_year, [subjectless_receipt.name]),
			1,
		)

	def test_cancel_receipt_records_audit_and_is_idempotent(self) -> None:
		donor, _contact = self._contact_donor("Cancelled")
		self._donation(donor.name, 80, f"{self.tax_year}-08-01")
		generate_receipts(self.company, self.tax_year)
		receipt = self._receipt(donor.name)

		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"receipt-manager-{self.suffix}@example.com",
				"first_name": "Receipt Manager",
				"enabled": 1,
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": "Non Profit Manager"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(manager.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				cancel_receipt(receipt.name, "Not authorized")
		finally:
			frappe.set_user("Administrator")

		result = cancel_receipt(receipt.name, "Donation was refunded")
		self.assertTrue(result["changed"])
		receipt.reload()
		self.assertEqual(receipt.status, "Cancelled")
		self.assertEqual(receipt.cancelled_by, "Administrator")
		self.assertEqual(receipt.cancellation_reason, "Donation was refunded")
		self.assertTrue(receipt.cancelled_on)
		self.assertFalse(cancel_receipt(receipt.name, "Ignored second reason")["changed"])

		with self.assertRaisesRegex(frappe.ValidationError, "reason is required"):
			cancel_receipt(receipt.name, "")
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[cancel_receipt], ["POST"])

	def _receipt(self, donor: str) -> Any:
		return frappe.get_doc(
			"Donation Tax Receipt",
			{"donor": donor, "tax_year": self.tax_year, "company": self.company},
		)


class TestDonationTaxReceiptEmailIssuance(TaxReceiptFixtures):
	"""Individual issuance ported from the retired `Donation Receipt.send_to_donor`."""

	def test_seeded_print_format_is_german_and_targets_the_tax_receipt(self) -> None:
		ensure_tax_receipt_print_format()
		values = frappe.db.get_value(
			"Print Format",
			DONATION_TAX_RECEIPT_PRINT_FORMAT,
			["doc_type", "disabled", "html"],
			as_dict=True,
		)
		self.assertEqual(values.doc_type, "Donation Tax Receipt")
		self.assertFalse(values.disabled)
		# German wording carried over from the retired Donation Receipt DE format.
		self.assertIn("Einzelspenden", values.html)
		self.assertIn("Es handelt sich nicht um den Verzicht", values.html)
		self.assertIn("Unterschrift des Zuwendungsempfängers", values.html)
		self.assertIn("donation_details", values.html)
		# German income-tax paragraphs must not travel to the Swiss receipt.
		self.assertNotIn("EStG", values.html)

	def test_email_sends_pdf_and_stamps_audit_field_without_changing_status(self) -> None:
		ensure_tax_receipt_print_format()
		donor, _contact = self._contact_donor("Gerda", email=f"gerda.{self.suffix}@example.org")
		self._donation(donor.name, 90, f"{self.tax_year}-04-01")
		generate_receipts(self.company, self.tax_year)
		receipt = self._receipt(donor.name)

		attachment = {"fname": "receipt.pdf", "fcontent": b"%PDF"}
		with (
			patch.object(frappe, "attach_print", return_value=attachment) as attach_print,
			patch("non_profit.non_profit.tax_receipts.send_referenced_email") as sendmail,
		):
			result = send_receipt_email(receipt.name)

		self.assertEqual(result["receipt"], receipt.name)
		self.assertEqual(result["email"], f"gerda.{self.suffix}@example.org")
		self.assertEqual(result["print_format"], DONATION_TAX_RECEIPT_PRINT_FORMAT)

		attach_print.assert_called_once()
		self.assertEqual(attach_print.call_args.kwargs["print_format"], DONATION_TAX_RECEIPT_PRINT_FORMAT)
		self.assertEqual(attach_print.call_args.kwargs["lang"], "de")

		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], [f"gerda.{self.suffix}@example.org"])
		self.assertEqual(kwargs["reference_doctype"], "Donation Tax Receipt")
		self.assertEqual(kwargs["reference_name"], receipt.name)
		self.assertEqual(kwargs["attachments"], [attachment])
		self.assertIn(str(self.tax_year), kwargs["subject"])

		receipt.reload()
		self.assertTrue(receipt.email_sent_on)
		# Emailing is not issuing: the annual `mark_receipts_issued` action owns that.
		self.assertEqual(receipt.status, "Draft")

	def test_email_requires_a_resolvable_donor_email(self) -> None:
		ensure_tax_receipt_print_format()
		donor, _contact = self._contact_donor("Heidi")
		self._donation(donor.name, 55, f"{self.tax_year}-04-02")
		generate_receipts(self.company, self.tax_year)
		receipt = self._receipt(donor.name)

		with (
			patch("non_profit.non_profit.tax_receipts.send_referenced_email") as sendmail,
			self.assertRaisesRegex(frappe.ValidationError, "no email address"),
		):
			send_receipt_email(receipt.name)
		sendmail.assert_not_called()
		receipt.reload()
		self.assertFalse(receipt.email_sent_on)

	def test_cancelled_receipts_cannot_be_emailed(self) -> None:
		ensure_tax_receipt_print_format()
		donor, _contact = self._contact_donor("Ivo", email=f"ivo.{self.suffix}@example.org")
		self._donation(donor.name, 65, f"{self.tax_year}-04-03")
		generate_receipts(self.company, self.tax_year)
		receipt = self._receipt(donor.name)
		cancel_receipt(receipt.name, "Test cancellation")

		with (
			patch("non_profit.non_profit.tax_receipts.send_referenced_email") as sendmail,
			self.assertRaisesRegex(frappe.ValidationError, "Draft or Issued"),
		):
			send_receipt_email(receipt.name)
		sendmail.assert_not_called()

	def _receipt(self, donor: str) -> Any:
		return frappe.get_doc(
			"Donation Tax Receipt",
			{"donor": donor, "tax_year": self.tax_year, "company": self.company},
		)


class TestDonationTaxReceiptCandidateRows(TaxReceiptFixtures):
	def test_provider_factory_contract(self) -> None:
		self.assertEqual(
			direct_mail_audience_provider(),
			{
				"key": "donation_tax_receipt",
				"label": "Donation Tax Receipts",
				"get_rows": "non_profit.non_profit.tax_receipts.direct_mail_candidate_rows",
			},
		)

	def test_rows_carry_producer_context_and_skip_subjectless_donors(self) -> None:
		donor, contact = self._contact_donor("Elsa")
		self._donation(donor.name, 120.5, f"{self.tax_year}-03-04")
		subjectless = self._subjectless_donor()
		self._donation(subjectless.name, 60, f"{self.tax_year}-03-05")
		generate_receipts(self.company, self.tax_year)

		rows = direct_mail_candidate_rows(receipt_campaign_reference(self.company, self.tax_year))
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["canonical_subject_type"], "Contact")
		self.assertEqual(row["canonical_subject"], contact.name)
		self.assertEqual(row["donor"], donor.name)
		context = row["producer_context"]
		self.assertEqual(context["tax_year"], str(self.tax_year))
		self.assertEqual(context["donation_count"], "1")
		self.assertIn("120.50", context["receipt_total"])
		self.assertIn("<table", context["donation_table_html"])
		self.assertIn("04.03.", context["donation_table_html"])
		self.assertTrue(context["receipt_name"].startswith("NPO-STR-"))

	def test_reference_must_carry_company_and_year(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "<company>\\|<tax_year>"):
			direct_mail_candidate_rows("just-a-company")

	def test_issued_receipts_are_not_returned_for_duplicate_postal_dispatch(self) -> None:
		donor, _contact = self._contact_donor("Already Issued")
		self._donation(donor.name, 85, f"{self.tax_year}-03-06")
		generate_receipts(self.company, self.tax_year)
		receipt = frappe.get_doc(
			"Donation Tax Receipt",
			{"donor": donor.name, "tax_year": self.tax_year, "company": self.company},
		)
		self.assertEqual(
			len(direct_mail_candidate_rows(receipt_campaign_reference(self.company, self.tax_year))), 1
		)
		mark_receipts_issued(self.company, self.tax_year, [receipt.name])
		self.assertEqual(
			direct_mail_candidate_rows(receipt_campaign_reference(self.company, self.tax_year)), []
		)

	def test_donation_table_renders_de_locale_rows(self) -> None:
		html = donation_table_html([{"date": "2026-03-04", "amount": 1250.0}])
		self.assertIn("<table", html)
		self.assertIn("04.03.2026", html)
		self.assertIn("250.00", html)


@skipUnless(GOOD_DIRECT_MAIL_AVAILABLE, "good_direct_mail is not installed")
class TestDonationTaxReceiptCampaign(TaxReceiptFixtures):
	def test_receipt_campaign_freezes_letters_with_receipt_values(self) -> None:
		from good_direct_mail.services.freeze import freeze_campaign
		from good_direct_mail.services.preparation import prepare_recipients

		donor, _contact = self._contact_donor("Fritz")
		self._donation(donor.name, 200, f"{self.tax_year}-03-04")
		company_address = self._address("Company", self.company, f"Company {self.suffix}")
		letter_head = self._letter_head()

		campaign_name = create_receipt_campaign(
			company=self.company,
			tax_year=self.tax_year,
			letter_head=letter_head,
			company_address=company_address.name,
		)
		campaign = frappe.get_doc("Good Direct Mail Campaign", campaign_name)
		self.assertEqual(campaign.source_provider, "donation_tax_receipt")
		self.assertEqual(campaign.source_reference, receipt_campaign_reference(self.company, self.tax_year))
		self.assertEqual(campaign.letter_category, "Official")
		self.assertFalse(campaign.include_payment_part)
		self.assertFalse(campaign.recipient_selection)

		prepare_recipients(campaign_name)
		campaign.reload()
		self.assertEqual(campaign.status, "Review")
		self.assertEqual(campaign.included_count, 1)

		freeze_campaign(campaign_name)
		campaign.reload()
		self.assertEqual(campaign.status, "Frozen")
		recipient = frappe.get_last_doc("Good Direct Mail Recipient", filters={"campaign": campaign_name})
		self.assertFalse(recipient.payment_part)
		self.assertEqual(recipient.letter_title_snapshot, f"Spendenbescheinigung {self.tax_year}")
		self.assertIn("200.00", recipient.letter_html_snapshot)
		# The producer table is trusted markup and must render unescaped.
		self.assertIn("<table", recipient.letter_html_snapshot)
		self.assertNotIn("&lt;table", recipient.letter_html_snapshot)
		self.assertIn("04.03.", recipient.letter_html_snapshot)

		with self.assertRaisesRegex(frappe.ValidationError, "already exists"):
			create_receipt_campaign(
				company=self.company,
				tax_year=self.tax_year,
				letter_head=letter_head,
				company_address=company_address.name,
			)

	def _letter_head(self) -> str:
		letter_head = frappe.get_doc(
			{
				"doctype": "Letter Head",
				"letter_head_name": f"Receipt {self.suffix}",
				"source": "HTML",
				"content": "<p>Goodvantage</p>",
				"footer_source": "HTML",
				"footer": "",
			}
		).insert(ignore_permissions=True)
		letter_head.source = "HTML"
		letter_head.content = "<p>Goodvantage</p>"
		letter_head.save(ignore_permissions=True)
		return letter_head.name


class TestLegacyDonationReceiptRemovalPatch(UnitTestCase):
	def test_patch_is_pre_model_sync_and_drops_only_allowlisted_tables(self) -> None:
		from non_profit.patches import drop_legacy_donation_receipt as removal

		with open(frappe.get_app_path("non_profit", "patches.txt")) as patches_file:
			pre_model_sync, post_model_sync = patches_file.read().split("[post_model_sync]")
		self.assertIn("non_profit.patches.drop_legacy_donation_receipt", pre_model_sync)
		self.assertNotIn("non_profit.patches.drop_legacy_donation_receipt", post_model_sync)

		with (
			patch.object(removal.frappe, "get_all", return_value=["Donation Receipt DE"]),
			patch.object(removal.frappe, "delete_doc") as delete_doc,
			patch.object(removal.frappe, "clear_cache") as clear_cache,
			patch.object(removal.frappe.db, "exists", return_value=True),
			patch.object(removal.frappe.db, "table_exists", return_value=True),
			patch.object(removal.frappe.db, "sql_ddl") as sql_ddl,
		):
			removal.execute()

		self.assertEqual(
			[call.args[:2] for call in delete_doc.call_args_list],
			[
				("Print Format", "Donation Receipt DE"),
				("DocType", removal.CHILD_DOCTYPE),
				("DocType", removal.PARENT_DOCTYPE),
			],
		)
		sql_ddl.assert_any_call("drop table `tabDonation Receipt Item`")
		sql_ddl.assert_any_call("drop table `tabDonation Receipt`")
		clear_cache.assert_called_once_with()

		with self.assertRaisesRegex(ValueError, "non-retired"):
			removal._drop_retired_table("Donation Tax Receipt")

	def test_patch_is_idempotent_when_legacy_model_is_absent(self) -> None:
		from non_profit.patches import drop_legacy_donation_receipt as removal

		with (
			patch.object(removal.frappe, "get_all", return_value=[]),
			patch.object(removal.frappe, "delete_doc") as delete_doc,
			patch.object(removal.frappe, "clear_cache"),
			patch.object(removal.frappe.db, "exists", return_value=False),
			patch.object(removal.frappe.db, "table_exists", return_value=False),
			patch.object(removal.frappe.db, "sql_ddl") as sql_ddl,
		):
			removal.execute()
		delete_doc.assert_not_called()
		sql_ddl.assert_not_called()
