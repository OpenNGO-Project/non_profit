from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from non_profit.www import donate


class TestDonateConfirmPage(FrappeTestCase):
	def test_confirm_page_requires_donation_key(self) -> None:
		from non_profit.non_profit.doctype.donation.test_donation import (
			create_donor,
			create_donor_type,
			get_company_and_accounts,
		)
		from non_profit.www import donate_confirm
		from non_profit.www.donate import donation_confirm_query

		company, _receivable, _cash = get_company_and_accounts()
		create_donor_type()
		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": "donor@test.com",
				"company": company,
				"date": frappe.utils.nowdate(),
				"amount": 42,
			}
		)
		donation.flags.ignore_permissions = True
		donation.insert()

		self.assertTrue(donation.confirmation_key, "before_insert must generate a confirmation key")
		self.assertIn(f"key={donation.confirmation_key}", donation_confirm_query(donation.name))

		previous_user = frappe.session.user
		original_form_dict = frappe.local.form_dict
		try:
			# Donation names are a sequential series — guests must not be able
			# to read donor name and amount by enumerating names.
			frappe.set_user("Guest")
			frappe.local.form_dict = frappe._dict({"donation": donation.name})
			self.assertIsNone(donate_confirm.get_context(frappe._dict()).donation)

			frappe.local.form_dict = frappe._dict({"donation": donation.name, "key": "wrong-key"})
			self.assertIsNone(donate_confirm.get_context(frappe._dict()).donation)

			frappe.local.form_dict = frappe._dict(
				{"donation": donation.name, "key": donation.confirmation_key}
			)
			context = donate_confirm.get_context(frappe._dict())
			self.assertIsNotNone(context.donation)
			self.assertEqual(context.donation.name, donation.name)

			# A logged-in user with read permission still sees the page
			# without the key (staff workflows).
			frappe.set_user("Administrator")
			frappe.local.form_dict = frappe._dict({"donation": donation.name})
			context = donate_confirm.get_context(frappe._dict())
			self.assertIsNotNone(context.donation)
		finally:
			frappe.set_user(previous_user)
			frappe.local.form_dict = original_form_dict


class TestDonatePage(FrappeTestCase):
	def test_guest_donation_requires_valid_captcha_when_configured(self) -> None:
		previous_user = frappe.session.user
		frappe.set_user("Guest")
		try:
			with patch("non_profit.www.donate._captcha_site_key", return_value="site-key"):
				with patch(
					"non_profit.www.donate.verify_goodvantage_captcha_response",
					return_value=False,
				) as verify:
					with self.assertRaises(frappe.ValidationError):
						donate._verify_captcha({donate.GOODVANTAGE_CAPTCHA_RESPONSE_FIELD: "bad-token"})
				verify.assert_called_once_with("bad-token")
		finally:
			frappe.set_user(previous_user)

	def test_guest_donation_allows_unconfigured_optional_captcha(self) -> None:
		previous_user = frappe.session.user
		frappe.set_user("Guest")
		try:
			with patch("non_profit.www.donate._captcha_site_key", return_value=""):
				with patch("non_profit.www.donate.verify_goodvantage_captcha_response") as verify:
					donate._verify_captcha({})
				verify.assert_not_called()
		finally:
			frappe.set_user(previous_user)


class TestHardenedWhitelistedMethods(FrappeTestCase):
	"""run_doc_method only enforces read permission; the four write-action doc
	methods must reject users without write access."""

	def _read_only_user(self) -> str:
		email = f"readonly-{frappe.generate_hash(length=8)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Read",
				"last_name": "Only",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)
		return email

	def test_write_actions_require_write_permission(self) -> None:
		from non_profit.non_profit.doctype.donation.test_donation import (
			create_donor,
			create_donor_type,
			get_company_and_accounts,
		)

		company, _receivable, _cash = get_company_and_accounts()
		create_donor_type()
		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": "donor@test.com",
				"company": company,
				"date": frappe.utils.nowdate(),
				"amount": 18,
			}
		)
		donation.flags.ignore_permissions = True
		donation.insert()
		donation.reload()
		donation.flags.ignore_permissions = False

		readonly = self._read_only_user()
		previous_user = frappe.session.user
		try:
			frappe.set_user(readonly)
			with self.assertRaises(frappe.PermissionError):
				donation.send_thank_you()
		finally:
			frappe.set_user(previous_user)

	def test_payment_reference_helpers_reject_foreign_doctypes(self) -> None:
		from non_profit.non_profit.custom_doctype.payment_entry import get_donation_payment_entry

		# Caller-controlled doctype must never become a generic document reader.
		with self.assertRaises(frappe.ValidationError):
			get_donation_payment_entry("Sales Invoice", "SINV-ANY")

	def test_payment_reference_details_require_read_permission(self) -> None:
		from non_profit.non_profit.custom_doctype.payment_entry import get_payment_reference_details
		from non_profit.non_profit.doctype.donation.test_donation import (
			create_donor,
			create_donor_type,
			get_company_and_accounts,
		)

		company, _receivable, _cash = get_company_and_accounts()
		create_donor_type()
		donor = create_donor()
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"email": "donor@test.com",
				"company": company,
				"date": frappe.utils.nowdate(),
				"amount": 27,
			}
		)
		donation.flags.ignore_permissions = True
		donation.insert()

		readonly = self._read_only_user()
		previous_user = frappe.session.user
		try:
			frappe.set_user(readonly)
			with self.assertRaises(frappe.PermissionError):
				get_payment_reference_details("Donation", donation.name, "CHF")
		finally:
			frappe.set_user(previous_user)


class TestGuestDonorProtection(FrappeTestCase):
	def test_guest_resubmission_adds_comment_instead_of_rename(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import find_donor_by_email
		from non_profit.www.donate import _handle_submission

		email = f"keepname-{frappe.generate_hash(length=8)}@example.com"
		first_form = frappe._dict(
			donor_name="Original Donor",
			email=email,
			amount="25",
			frequency="one_off",
			consent="1",
		)
		with patch("non_profit.www.donate._verify_captcha"):
			_handle_submission(first_form)

		donor_name = find_donor_by_email(email)
		self.assertTrue(donor_name)

		second_form = frappe._dict(
			donor_name="Defaced Donor",
			email=email,
			amount="30",
			frequency="one_off",
			consent="1",
		)
		with patch("non_profit.www.donate._verify_captcha"):
			_handle_submission(second_form)

		self.assertEqual(
			frappe.db.get_value("Donor", donor_name, "donor_name"),
			"Original Donor",
		)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Donor", "reference_name": donor_name},
			pluck="content",
		)
		self.assertTrue(any("Defaced Donor" in (content or "") for content in comments))
