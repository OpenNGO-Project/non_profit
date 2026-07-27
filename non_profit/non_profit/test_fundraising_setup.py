from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.non_profit import fundraising_setup


class TestFundraisingSetup(IntegrationTestCase):
	PRINT_FORMATS = (
		(
			"Donation Receipt DE",
			"DONATION_RECEIPT_DE_HTML",
			fundraising_setup.ensure_print_format,
		),
		(
			"Donation Slip CH",
			"DONATION_SLIP_CH_HTML",
			fundraising_setup.ensure_swiss_qrbill_print_format,
		),
	)

	def test_updates_untouched_seed_when_shipped_content_changes(self) -> None:
		for name, constant_name, ensure in self.PRINT_FORMATS:
			with self.subTest(print_format=name):
				original_html = getattr(fundraising_setup, constant_name)
				revised_html = f"{original_html}\n<!-- revised shipped content -->"
				frappe.db.set_value("Print Format", name, "html", original_html, update_modified=False)

				with patch.object(fundraising_setup, constant_name, revised_html):
					ensure()

				self.assertEqual(frappe.db.get_value("Print Format", name, "html"), revised_html)

	def test_preserves_operator_edited_seed(self) -> None:
		operator_html = "<p>Operator-owned print format</p>"
		for name, constant_name, ensure in self.PRINT_FORMATS:
			with self.subTest(print_format=name):
				revised_html = f"{getattr(fundraising_setup, constant_name)}\n<!-- revised -->"
				frappe.db.set_value("Print Format", name, "html", operator_html, update_modified=False)

				with patch.object(fundraising_setup, constant_name, revised_html):
					ensure()

				self.assertEqual(frappe.db.get_value("Print Format", name, "html"), operator_html)

	def test_email_template_remains_create_only(self) -> None:
		operator_html = "<p>Operator-owned thank-you email</p>"
		frappe.db.set_value(
			"Email Template", "Donation Thank You DE", "response", operator_html, update_modified=False
		)

		fundraising_setup.ensure_email_template()

		self.assertEqual(
			frappe.db.get_value("Email Template", "Donation Thank You DE", "response"), operator_html
		)
