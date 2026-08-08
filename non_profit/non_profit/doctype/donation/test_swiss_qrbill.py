"""``swiss_qrbill`` is a dispatch seam, not a renderer.

The standalone ``qrbill`` fallback that used to live here was removed: it could
forward a stored QRR without first proving that the creditor account was a
QR-IBAN, used a separate validation path, and hardcoded German. Rendering now
belongs to whichever app registers
``non_profit_qr_bill_svg_providers``. What this repository still owns, and what
these tests pin, is the seam:
first non-empty answer wins, a broken provider never reaches the print format,
and no provider means no slip rather than a fabricated one.
"""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

DOC = frappe._dict(doctype="Donation", name="DON-SEAM-001", amount=50)


class TestSwissQRBillSeam(UnitTestCase):
	def test_no_provider_renders_no_slip(self) -> None:
		# A print format must render without a payment part rather than show a
		# fabricated one; "" is what the Jinja helper puts in the template.
		with patch("non_profit.non_profit.swiss_qrbill.frappe.get_hooks", return_value=[]):
			self.assertEqual(swiss_qrbill_svg(DOC), "")

	def test_first_non_empty_provider_wins(self) -> None:
		with (
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_hooks",
				return_value=["empty.provider", "real.provider", "later.provider"],
			),
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_attr",
				side_effect=lambda path: {
					"empty.provider": lambda doc: "",
					"real.provider": lambda doc: "<svg id='real'/>",
					"later.provider": lambda doc: "<svg id='later'/>",
				}[path],
			),
		):
			self.assertEqual(swiss_qrbill_svg(DOC), "<svg id='real'/>")

	def test_failing_provider_is_logged_and_does_not_reach_the_print_format(self) -> None:
		# A provider raising must not crash printing; the next one still answers.
		def _boom(doc):
			raise ValueError("provider exploded")

		with (
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_hooks",
				return_value=["broken.provider", "real.provider"],
			),
			patch(
				"non_profit.non_profit.swiss_qrbill.frappe.get_attr",
				side_effect=lambda path: {
					"broken.provider": _boom,
					"real.provider": lambda doc: "<svg id='real'/>",
				}[path],
			),
			patch("non_profit.non_profit.swiss_qrbill.frappe.log_error") as log_error,
		):
			self.assertEqual(swiss_qrbill_svg(DOC), "<svg id='real'/>")
		log_error.assert_called_once()

	def test_retryable_provider_error_propagates_without_logging(self) -> None:
		for error_type in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			with self.subTest(error_type=error_type):
				error = error_type("retry QR-bill provider")

				def raise_error(doc):
					raise error

				with (
					patch(
						"non_profit.non_profit.swiss_qrbill.frappe.get_hooks",
						return_value=["provider.path"],
					),
					patch(
						"non_profit.non_profit.swiss_qrbill.frappe.get_attr",
						return_value=raise_error,
					),
					patch("non_profit.non_profit.swiss_qrbill.frappe.log_error") as log_error,
					self.assertRaises(error_type) as raised,
				):
					swiss_qrbill_svg(DOC)

				self.assertIs(raised.exception, error)
				log_error.assert_not_called()

	def test_this_repository_renders_nothing_itself(self) -> None:
		# The public repo must not grow a second QR engine again: no QR library
		# import, and no renderer behind the dispatch loop.
		import non_profit.non_profit.swiss_qrbill as seam

		source = frappe.read_file(seam.__file__) or ""
		self.assertNotIn("qrbill import", source)
		self.assertNotIn("QRBill(", source)
