from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.www import donate

DONATE_PAGES_FLAG = "enable_non_profit_public_donate_pages"


@contextmanager
def public_donate_pages_enabled():
	"""Serve the generic /donate pages for the duration of the test."""
	previous = frappe.conf.get(DONATE_PAGES_FLAG)
	frappe.conf[DONATE_PAGES_FLAG] = 1
	try:
		yield
	finally:
		if previous is None:
			frappe.conf.pop(DONATE_PAGES_FLAG, None)
		else:
			frappe.conf[DONATE_PAGES_FLAG] = previous


class TestGenericDonatePagesGate(IntegrationTestCase):
	"""The generic, unbranded /donate flow is opt-in per site."""

	def test_pages_are_hidden_by_default(self) -> None:
		from non_profit.www import donate_confirm

		self.assertFalse(donate.public_donate_pages_enabled())
		with self.assertRaises(frappe.DoesNotExistError):
			donate.get_context(frappe._dict())
		with self.assertRaises(frappe.DoesNotExistError):
			donate_confirm.get_context(frappe._dict())

	def test_disabled_page_refuses_submissions(self) -> None:
		# The POST handler runs inside get_context; the gate must come first so
		# a hidden page cannot still create Donors and Donations.
		handle = MagicMock()
		with (
			patch("non_profit.www.donate.frappe.request", frappe._dict(method="POST")),
			patch("non_profit.www.donate._handle_submission", handle),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				donate.get_context(frappe._dict())
		handle.assert_not_called()

	def test_hidden_pages_answer_a_real_404_status(self) -> None:
		# The exception class is not the contract — the HTTP status is. Both
		# DoesNotExistError and PageDoesNotExistError render the 404 body, but
		# the latter leaves the status at 200, which reads as "page exists" to
		# crawlers, monitors and caches. Asserting the status keeps a swap of
		# the exception class from silently un-hiding the page.
		from frappe.website.serve import get_response

		for path in ("/donate", "/donate_confirm"):
			response = get_response(path)
			self.assertEqual(response.status_code, 404, f"{path} did not answer 404")

	def test_site_config_flag_serves_the_pages(self) -> None:
		with public_donate_pages_enabled():
			self.assertTrue(donate.public_donate_pages_enabled())
			with patch("non_profit.www.donate._get_active_campaigns", return_value=[]):
				context = donate.get_context(frappe._dict())
			self.assertEqual(context.campaigns, [])


class TestDonateConfirmPage(IntegrationTestCase):
	def test_confirm_page_requires_donation_key(self) -> None:
		from non_profit.non_profit.doctype.donation.test_donation import (
			create_donor,
			create_donor_type,
			get_company_and_accounts,
		)
		from non_profit.www import donate_confirm
		from non_profit.www.donate import donation_confirm_query

		self.enterContext(public_donate_pages_enabled())
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


class TestDonatePage(IntegrationTestCase):
	def test_unconfigured_captcha_disables_public_donation_submit(self) -> None:
		template = (Path(__file__).parent / "www" / "donate.html").read_text(encoding="utf-8")
		self.assertIn("CAPTCHA is not configured. Please contact support.", template)
		self.assertIn('data-testid="donate-submit" disabled', template)

	def test_confirm_page_escapes_guest_controlled_donor_name(self) -> None:
		# donor_name is guest-supplied and this page is reachable by anyone
		# holding the confirmation-key link; Frappe website Jinja does not
		# autoescape, so the field must carry the escape filter.
		template = (Path(__file__).parent / "www" / "donate_confirm.html").read_text(encoding="utf-8")
		self.assertIn("donation.donor_name | e", template)
		self.assertNotIn("{{ donation.donor_name }}", template)

	def test_captcha_loader_state_controls_submit_and_supports_retry(self) -> None:
		template = (Path(__file__).parent / "www" / "donate.html").read_text(encoding="utf-8")
		self.assertIn("new MutationObserver(syncSubmitState)", template)
		self.assertIn('state !== "loaded"', template)
		self.assertIn('wrapper.dataset.loadState = "retrying"', template)
		self.assertIn('wrapper.dataset.loadState = "error"', template)
		self.assertIn('retry.className = "gv-captcha-retry"', template)
		self.assertIn("mountGoodvantageCaptcha(selector, siteKey, {", template)

	def test_guest_donation_requires_valid_captcha_when_configured(self) -> None:
		previous_user = frappe.session.user
		frappe.set_user("Guest")
		verify = MagicMock(return_value=False)
		backend = {
			"response_field": donate.DEFAULT_CAPTCHA_RESPONSE_FIELD,
			"site_key": lambda: "site-key",
			"verify": verify,
		}
		try:
			with patch("non_profit.www.donate._captcha_backend", return_value=backend):
				with self.assertRaises(frappe.ValidationError):
					donate._verify_captcha({donate.DEFAULT_CAPTCHA_RESPONSE_FIELD: "bad-token"})
			verify.assert_called_once_with("bad-token")
		finally:
			frappe.set_user(previous_user)

	def test_guest_donation_fails_closed_when_captcha_is_unconfigured(self) -> None:
		previous_user = frappe.session.user
		frappe.set_user("Guest")
		try:
			with patch("non_profit.www.donate._captcha_backend", return_value={}):
				with self.assertRaises(frappe.ValidationError) as error:
					donate._verify_captcha({})
				self.assertIn("CAPTCHA is not configured", str(error.exception))
		finally:
			frappe.set_user(previous_user)

	def test_guest_donation_does_not_hide_captcha_configuration_errors(self) -> None:
		def broken_site_key():
			raise frappe.ValidationError("invalid CAPTCHA configuration")

		backend = {"site_key": broken_site_key, "verify": MagicMock()}
		with patch("non_profit.www.donate._captcha_backend", return_value=backend):
			with self.assertRaisesRegex(frappe.ValidationError, "invalid CAPTCHA configuration"):
				donate._captcha_site_key()

	def test_public_campaign_requires_active_cost_center_in_donation_company(self) -> None:
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "Donation Campaign":
				return frappe._dict(status="Active", cost_center="CROSS-COMPANY")
			if doctype == "Cost Center":
				return frappe._dict(company="Other Company", is_group=0, disabled=0)
			raise AssertionError((doctype, name, fields, kwargs))

		with patch.object(frappe.db, "get_value", side_effect=get_value):
			self.assertFalse(donate.campaign_matches_company("CAMPAIGN", "Donation Company"))

	def test_public_campaign_options_are_scoped_to_company_cost_centers(self) -> None:
		with (
			patch("non_profit.www.donate._resolve_donation_company", return_value="Donation Company"),
			patch.object(frappe, "get_all", side_effect=[["CC-DONATION"], []]) as get_all,
		):
			self.assertEqual(donate._get_active_campaigns(), [])

		campaign_filters = get_all.call_args_list[1].kwargs["filters"]
		self.assertEqual(campaign_filters["cost_center"], ["in", ["CC-DONATION"]])


class TestHardenedWhitelistedMethods(IntegrationTestCase):
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


def _without_checkout_provider():
	"""Exercise non_profit's own recording path.

	With a payment integration installed, `/donate` delegates the whole
	collection path to it and redirects the donor to a hosted checkout. These
	tests are about what this app does on its own, so the seam is closed.
	"""
	from unittest.mock import patch

	return patch("non_profit.www.donate._delegate_public_checkout", return_value=None)


class TestGuestDonationAmountInvariant(IntegrationTestCase):
	"""`float()` happily parses "inf"/"nan"/"1e400", and `nan <= 0` is False, so
	the positivity check alone let a guest persist a non-finite Donation amount
	that then flowed into totals, allocations and receipts."""

	def test_guest_submission_rejects_non_finite_amounts(self) -> None:
		from non_profit.www.donate import _handle_submission

		for raw_amount in ("inf", "-inf", "1e400", "nan", "NaN", "Infinity"):
			with self.subTest(amount=raw_amount):
				email = f"nonfinite-{frappe.generate_hash(length=8)}@example.com"
				form = frappe._dict(
					donor_name="Non Finite Donor",
					email=email,
					amount=raw_amount,
					frequency="one_off",
					consent="1",
				)
				with patch("non_profit.www.donate._verify_captcha"):
					with self.assertRaises(frappe.ValidationError):
						with _without_checkout_provider():
							_handle_submission(form)

				self.assertFalse(
					frappe.db.exists("Donation", {"email": email}),
					f"{raw_amount!r} must not create a Donation",
				)

	def test_guest_submission_still_accepts_a_normal_amount(self) -> None:
		from non_profit.www.donate import _handle_submission

		email = f"finite-{frappe.generate_hash(length=8)}@example.com"
		form = frappe._dict(
			donor_name="Finite Donor",
			email=email,
			amount="12.50",
			frequency="one_off",
			consent="1",
		)
		with patch("non_profit.www.donate._verify_captcha"):
			with _without_checkout_provider():
				donation_name = _handle_submission(form)

		self.assertEqual(frappe.db.get_value("Donation", donation_name, "amount"), 12.50)


class TestGuestDonorProtection(IntegrationTestCase):
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
			with _without_checkout_provider():
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
			with _without_checkout_provider():
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
