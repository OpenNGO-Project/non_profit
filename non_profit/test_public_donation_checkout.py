"""The public /donate page must collect money, not merely record a promise.

Before this seam the page created a Donation (and, for a recurring gift, a
schedule) and redirected the donor to a confirmation page without ever taking a
payment. non_profit is public and cannot build a checkout itself, so it
delegates to whichever payment integration is installed.
"""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.www import donate


class TestPublicCheckoutDelegation(UnitTestCase):
	def test_a_provider_url_redirects_the_donor_to_pay(self):
		with (
			patch.object(frappe, "get_hooks", return_value=["dummy.provider"]),
			patch.object(frappe, "get_attr", return_value=lambda **_: "https://pay.example.test/x"),
			self.assertRaises(frappe.Redirect),
		):
			donate._delegate_public_checkout(amount=50, frequency="Monthly")

		self.assertEqual(frappe.local.flags.redirect_location, "https://pay.example.test/x")

	def test_no_provider_falls_back_to_recording_only(self):
		"""Standalone non_profit keeps its historical behaviour."""
		with patch.object(frappe, "get_hooks", return_value=[]):
			self.assertIsNone(donate._delegate_public_checkout(amount=50, frequency="one_off"))

	def test_a_provider_returning_nothing_falls_through(self):
		with (
			patch.object(frappe, "get_hooks", return_value=["dummy.provider"]),
			patch.object(frappe, "get_attr", return_value=lambda **_: None),
		):
			self.assertIsNone(donate._delegate_public_checkout(amount=50, frequency="one_off"))

	def test_a_failing_provider_is_not_swallowed(self):
		"""Telling a donor their gift is set up when no checkout happened is worse."""

		def broken(**_):
			raise ValueError("provider down")

		with (
			patch.object(frappe, "get_hooks", return_value=["dummy.provider"]),
			patch.object(frappe, "get_attr", return_value=broken),
			self.assertRaises(ValueError),
		):
			donate._delegate_public_checkout(amount=50, frequency="Monthly")

	def test_the_page_offers_one_off_and_monthly_only(self):
		"""Quarterly and yearly stay with staff; fewer public options convert better."""
		import pathlib

		template = pathlib.Path(donate.__file__).with_name("donate.html").read_text()
		self.assertIn('value="one_off"', template)
		self.assertIn('value="Monthly"', template)
		self.assertNotIn('value="Quarterly"', template)
		self.assertNotIn('value="Yearly"', template)

	def test_the_amount_label_is_not_hardcoded_to_euros(self):
		import pathlib

		template = pathlib.Path(donate.__file__).with_name("donate.html").read_text()
		self.assertNotIn("Betrag (EUR)", template)

	def test_the_page_preserves_a_provider_idempotency_key(self):
		import pathlib

		template = pathlib.Path(donate.__file__).with_name("donate.html").read_text()
		self.assertIn('name="request_key"', template)
		self.assertIn("recurring_request_key", template)
