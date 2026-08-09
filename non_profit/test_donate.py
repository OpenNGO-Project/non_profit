from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
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


@contextmanager
def frappe_user(user: str):
	previous_user = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous_user)


def identity_master_counts() -> dict[str, int]:
	return {
		doctype: frappe.db.count(doctype)
		for doctype in (
			"Donor Type",
			"Donor",
			"Customer",
			"Contact",
			"Address",
			"Dynamic Link",
			"Comment",
			"Donation",
			"Recurring Donation",
		)
	}


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
	def test_validation_redisplay_rolls_back_partial_submission_writes(self) -> None:
		donor_type = f"_Test Rolled Back Public Donation {frappe.generate_hash(length=8)}"

		def partially_write_then_fail(_form):
			frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type}).insert(
				ignore_permissions=True
			)
			frappe.throw("late validation failure")

		context = frappe._dict()
		with (
			public_donate_pages_enabled(),
			patch("non_profit.www.donate.frappe.request", frappe._dict(method="POST")),
			patch("non_profit.www.donate._captcha_site_key", return_value="site-key"),
			patch("non_profit.www.donate._handle_submission", side_effect=partially_write_then_fail),
			patch("non_profit.www.donate._get_active_campaigns", return_value=[]),
		):
			donate.get_context(context)

		self.assertIn("late validation failure", context.error)
		self.assertFalse(frappe.db.exists("Donor Type", donor_type))

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
	def test_guest_submission_rejects_ambiguous_donor_identity(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import find_donor_customer_candidates
		from non_profit.www.donate import _handle_submission

		email = f"ambiguous-guest-{frappe.generate_hash(length=8)}@example.com"
		donor_type = frappe.db.get_value("Donor Type", {}, "name")
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		identity_names = {"Donor": [], "Customer": []}
		for index in range(2):
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"Ambiguous Guest {index} {frappe.generate_hash(length=6)}",
					"customer_type": "Individual",
					"customer_group": customer_group,
					"territory": territory,
					"email_id": email,
				}
			).insert(ignore_permissions=True)
			identity_names["Customer"].append(customer.name)
			donor = frappe.get_doc(
				{
					"doctype": "Donor",
					"donor_name": f"Ambiguous Guest {index}",
					"donor_type": donor_type,
					"customer": customer.name,
				}
			).insert(ignore_permissions=True)
			identity_names["Donor"].append(donor.name)
		masters_before = {
			("Donor", name): frappe.db.get_value(
				"Donor", name, ["donor_name", "customer", "modified"], as_dict=True
			)
			for name in identity_names["Donor"]
		}
		masters_before.update(
			{
				("Customer", name): frappe.db.get_value(
					"Customer", name, ["customer_name", "email_id", "modified"], as_dict=True
				)
				for name in identity_names["Customer"]
			}
		)

		form = frappe._dict(
			donor_name="Ambiguous Guest",
			email=email,
			amount="25",
			frequency="one_off",
			consent="1",
		)
		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			patch("non_profit.non_profit.donor_identity.frappe.logger") as app_logger,
			patch("non_profit.non_profit.donor_identity.frappe.log_error") as error_log,
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
			_without_checkout_provider(),
		):
			_handle_submission(form)

		self.assertFalse(frappe.db.exists("Donation", {"email": email}))
		masters_after = {
			("Donor", name): frappe.db.get_value(
				"Donor", name, ["donor_name", "customer", "modified"], as_dict=True
			)
			for name in identity_names["Donor"]
		}
		masters_after.update(
			{
				("Customer", name): frappe.db.get_value(
					"Customer", name, ["customer_name", "email_id", "modified"], as_dict=True
				)
				for name in identity_names["Customer"]
			}
		)
		self.assertEqual(masters_after, masters_before)
		donor_names, customer_names = find_donor_customer_candidates(email)
		self.assertEqual(set(donor_names), set(identity_names["Donor"]))
		self.assertEqual(set(customer_names), set(identity_names["Customer"]))
		app_logger.assert_called_once_with("non_profit")
		error_log.assert_not_called()
		log_message = app_logger.return_value.warning.call_args.args[0]
		self.assertNotIn(email, log_message)
		self.assertIn(sha256(email.encode()).hexdigest(), log_message)

	def test_guest_submission_reuses_contact_only_donor(self) -> None:
		from non_profit.www.donate import _handle_submission

		email = f"contact-only-guest-{frappe.generate_hash(length=8)}@example.com"
		contact = self._contact("Contact Only Guest", email)
		donor = self._donor("Contact Only Guest", contact=contact.name)
		donor_count = frappe.db.count("Donor")

		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			_without_checkout_provider(),
		):
			donation_name = _handle_submission(self._form("Contact Only Guest", email))

		self.assertEqual(frappe.db.get_value("Donation", donation_name, "donor"), donor.name)
		self.assertEqual(frappe.db.count("Donor"), donor_count)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "contact"), contact.name)
		self.assertTrue(frappe.db.get_value("Donor", donor.name, "customer"))

	def test_guest_submission_reuses_canonical_contact_when_customer_email_differs(self) -> None:
		from non_profit.www.donate import _handle_submission

		email = f"canonical-contact-guest-{frappe.generate_hash(length=8)}@example.com"
		contact = self._contact("Canonical Contact Guest", email)
		customer = self._customer(
			"Canonical Contact Guest",
			f"different-{frappe.generate_hash(length=8)}@example.com",
		)
		donor = self._donor("Canonical Contact Guest", contact=contact.name, customer=customer.name)
		counts_before = {doctype: frappe.db.count(doctype) for doctype in ("Donor", "Customer")}

		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			_without_checkout_provider(),
		):
			donation_name = _handle_submission(self._form("Canonical Contact Guest", email))

		self.assertEqual(frappe.db.get_value("Donation", donation_name, "donor"), donor.name)
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in counts_before},
			counts_before,
		)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "customer"), customer.name)

	def test_guest_submission_rejects_duplicate_canonical_contact_donors_without_mutation(self) -> None:
		from non_profit.www.donate import _handle_submission

		email = f"duplicate-contact-donors-{frappe.generate_hash(length=8)}@example.com"
		donors = [
			self._donor(
				f"Duplicate Contact Guest {index}", contact=self._contact(f"Duplicate {index}", email).name
			)
			for index in range(2)
		]
		counts_before = identity_master_counts()
		donor_rows_before = {
			donor.name: frappe.db.get_value(
				"Donor", donor.name, ["donor_name", "customer", "contact", "modified"], as_dict=True
			)
			for donor in donors
		}

		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
			_without_checkout_provider(),
		):
			_handle_submission(self._form("Duplicate Contact Guest", email))

		self.assertEqual(identity_master_counts(), counts_before)
		self.assertEqual(
			{
				donor.name: frappe.db.get_value(
					"Donor", donor.name, ["donor_name", "customer", "contact", "modified"], as_dict=True
				)
				for donor in donors
			},
			donor_rows_before,
		)

	def test_guest_website_rejects_unrelated_same_email_customer_without_mutation(self) -> None:
		email = f"unrelated-customer-guest-{frappe.generate_hash(length=8)}@example.com"
		contact = self._contact("Unrelated Customer Guest", email)
		donor = self._donor("Unrelated Customer Guest", contact=contact.name)
		customer = self._customer(
			"Unrelated Customer",
			email,
			primary_contact=contact.name,
			customer_type="Company",
			subject_type="Organization",
		)
		counts_before = identity_master_counts()
		donor_before = frappe.db.get_value(
			"Donor", donor.name, ["donor_name", "customer", "contact", "modified"], as_dict=True
		)
		customer_before = frappe.db.get_value(
			"Customer",
			customer.name,
			["customer_name", "email_id", "customer_primary_contact", "modified"],
			as_dict=True,
		)
		form = self._form("Unrelated Customer Guest", email)
		context = frappe._dict()
		request_savepoint = f"guest_website_identity_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(request_savepoint)
		rollback = frappe.db.rollback
		original_form_dict = frappe.local.form_dict
		original_request_ip = frappe.local.request_ip
		try:
			with (
				frappe_user("Guest"),
				public_donate_pages_enabled(),
				patch("non_profit.www.donate.frappe.request", frappe._dict(method="POST")),
				patch("non_profit.www.donate._captcha_site_key", return_value="site-key"),
				patch("non_profit.www.donate._verify_captcha"),
				patch("non_profit.www.donate._get_active_campaigns", return_value=[]),
				patch(
					"non_profit.www.donate.frappe.db.rollback",
					side_effect=lambda: rollback(save_point=request_savepoint),
				) as request_rollback,
			):
				frappe.local.form_dict = form
				frappe.local.request_ip = "192.0.2.10"
				donate.get_context(context)
		finally:
			frappe.local.form_dict = original_form_dict
			frappe.local.request_ip = original_request_ip

		self.assertIn("could not process your donation", context.error)
		request_rollback.assert_called_once_with()
		self.assertEqual(identity_master_counts(), counts_before)
		self.assertEqual(
			frappe.db.get_value(
				"Donor", donor.name, ["donor_name", "customer", "contact", "modified"], as_dict=True
			),
			donor_before,
		)
		self.assertEqual(
			frappe.db.get_value(
				"Customer",
				customer.name,
				["customer_name", "email_id", "customer_primary_contact", "modified"],
				as_dict=True,
			),
			customer_before,
		)

	def test_guest_submission_accepts_proven_donor_customer_identity(self) -> None:
		from non_profit.www.donate import _handle_submission

		email = f"proven-customer-guest-{frappe.generate_hash(length=8)}@example.com"
		contact = self._contact("Proven Customer Guest", email)
		customer = self._customer("Proven Customer Guest", email, primary_contact=contact.name)
		donor = self._donor("Proven Customer Guest", contact=contact.name)

		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			_without_checkout_provider(),
		):
			donation_name = _handle_submission(self._form("Proven Customer Guest", email))

		self.assertEqual(frappe.db.get_value("Donation", donation_name, "donor"), donor.name)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "customer"), customer.name)

	def test_guest_submission_fails_closed_without_creating_missing_donor_type(self) -> None:
		from non_profit.www.donate import _handle_submission, _resolve_donation_company

		email = f"missing-donor-type-{frappe.generate_hash(length=8)}@example.com"
		missing_donor_type = f"Missing Donor Type {frappe.generate_hash(length=8)}"
		company = _resolve_donation_company()
		self.assertTrue(company)
		counts_before = identity_master_counts()
		settings = frappe._dict(default_donor_type=missing_donor_type, donation_company=company)

		with (
			frappe_user("Guest"),
			patch("non_profit.www.donate._verify_captcha"),
			patch("non_profit.www.donate.frappe.get_single", return_value=settings),
			self.assertRaisesRegex(frappe.ValidationError, "setup is incomplete"),
			_without_checkout_provider(),
		):
			_handle_submission(self._form("Missing Donor Type Guest", email))

		self.assertEqual(identity_master_counts(), counts_before)
		self.assertFalse(frappe.db.exists("Donor Type", missing_donor_type))

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

	def _contact(self, name: str, email: str):
		first_name, _, last_name = name.partition(" ")
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": last_name,
				"npo_identity_kind": "Person",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

	def _customer(
		self,
		name: str,
		email: str,
		*,
		primary_contact: str | None = None,
		customer_type: str = "Individual",
		subject_type: str | None = None,
	):
		subject_type = subject_type or ("Person" if primary_contact else None)
		return frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": customer_type,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"email_id": email,
				"customer_primary_contact": primary_contact,
				"npo_subject_type": subject_type,
				"npo_contact": primary_contact if subject_type == "Person" else None,
			}
		).insert(ignore_permissions=True)

	def _donor(self, name: str, *, contact: str | None = None, customer: str | None = None):
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": name,
				"donor_type": frappe.db.get_value("Donor Type", {}, "name"),
				"subject_type": "Individual",
				"contact": contact,
				"customer": customer,
			}
		).insert(ignore_permissions=True)

	def _form(self, donor_name: str, email: str) -> frappe._dict:
		return frappe._dict(
			donor_name=donor_name,
			email=email,
			amount="25",
			frequency="one_off",
			consent="1",
		)
