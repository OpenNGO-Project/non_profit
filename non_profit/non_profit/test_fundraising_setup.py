from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from non_profit import hooks as non_profit_hooks
from non_profit import setup as non_profit_setup
from non_profit.non_profit import fundraising_setup, major_gifts


class TestFundraisingSetup(IntegrationTestCase):
	PRINT_FORMATS = (
		(
			fundraising_setup.DONATION_TAX_RECEIPT_PRINT_FORMAT,
			"DONATION_TAX_RECEIPT_DE_HTML",
			fundraising_setup.ensure_tax_receipt_print_format,
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

	def test_donor_controlled_fields_are_escaped_in_shipped_templates(self) -> None:
		# donor_name/email are guest-supplied (www/donate.py) and stored verbatim.
		# Frappe print-format and website Jinja render with autoescape OFF, so the
		# shipped bodies must escape them explicitly or a hostile name executes
		# script in the staff print session.
		payload = "<img src=x onerror=alert(1)>"
		doc = frappe._dict(
			name="DON-XSS-0001",
			donor_name=payload,
			email="donor@example.com",
			amount=42,
			total_amount=42,
			tax_year=2026,
			currency="CHF",
			campaign=None,
			date="2026-01-01",
			period_from="2026-01-01",
			period_to="2026-12-31",
			issued_on=None,
			creation="2026-01-01",
			donation_details="[]",
			remarks="",
			donations=[],
			qr_bill_svg="",
		)
		for constant_name in (
			"DONATION_SLIP_CH_HTML",
			"DONATION_TAX_RECEIPT_DE_HTML",
			"THANK_YOU_EMAIL_HTML",
		):
			with self.subTest(template=constant_name):
				rendered = frappe.render_template(  # nosemgrep
					getattr(fundraising_setup, constant_name), {"doc": doc}
				)
				self.assertNotIn(payload, rendered)
				self.assertIn("&lt;img", rendered)

	def test_donation_slip_zeroes_the_page_margins_it_depends_on(self) -> None:
		"""The slip declares `@page { margin: 0 }` and lays out a 210mm-wide payment
		part. Frappe sets wkhtmltopdf's page margins solely from the longhand
		properties on a `.print-format` rule, and an undeclared edge falls back to
		15mm — which would clip the payment reference a payer types into e-banking.

		Checked against Frappe's own parser rather than a copy of it. `non_profit`
		cannot import `good_connector`, so this does not share that app's helper.
		"""
		from bs4 import BeautifulSoup
		from frappe.utils.pdf import get_print_format_styles

		from non_profit.non_profit.fundraising_setup import DONATION_SLIP_CH_HTML

		declared = {
			style.name: style.value
			for style in get_print_format_styles(BeautifulSoup(DONATION_SLIP_CH_HTML, "html5lib"))
		}
		for edge in ("top", "right", "bottom", "left"):
			with self.subTest(margin=edge):
				value = declared.get(f"margin-{edge}")
				self.assertIsNotNone(value, f"margin-{edge} is not declared on .print-format")
				self.assertEqual(float(str(value).removesuffix("mm")), 0.0)

	def test_thank_you_email_formats_the_donation_company_currency(self) -> None:
		# The former shipped body hardcoded EUR on a CHF Swiss stack. Donation has
		# no currency field, so the company default currency is the contract.
		company = frappe.db.get_value("Company", {}, "name")
		currency = frappe.db.get_value("Company", company, "default_currency")
		rendered = frappe.render_template(  # nosemgrep
			fundraising_setup.THANK_YOU_EMAIL_HTML,
			{"doc": frappe._dict(donor_name="Amsale Test", amount=200, company=company, campaign=None)},
		)
		self.assertIn(frappe.utils.fmt_money(200, currency=currency), rendered)
		self.assertNotIn("EUR", fundraising_setup.THANK_YOU_EMAIL_HTML)

	def test_email_template_remains_create_only(self) -> None:
		operator_html = "<p>Operator-owned thank-you email</p>"
		frappe.db.set_value(
			"Email Template", "Donation Thank You DE", "response", operator_html, update_modified=False
		)

		fundraising_setup.ensure_email_template()

		self.assertEqual(
			frappe.db.get_value("Email Template", "Donation Thank You DE", "response"), operator_html
		)

	def test_after_app_install_dispatches_only_for_workflow_visualizer(self) -> None:
		self.assertEqual(non_profit_hooks.after_app_install, "non_profit.setup.after_app_install")

		with patch.object(major_gifts, "ensure_major_gift_workflow") as ensure_workflow:
			non_profit_setup.after_app_install("good_connector")
			ensure_workflow.assert_not_called()

			non_profit_setup.after_app_install("workflow_visualizer")
			ensure_workflow.assert_called_once_with()

	def test_workflow_visualizer_opt_in_is_idempotent(self) -> None:
		workflow_meta = frappe._dict(has_field=lambda fieldname: fieldname == "visible_on_doctype")
		with (
			patch.object(frappe, "get_meta", return_value=workflow_meta),
			patch.object(frappe.db, "get_value", side_effect=[0, 1]),
			patch.object(frappe.db, "set_value") as set_value,
		):
			major_gifts._ensure_workflow_visualizer_opt_in()
			major_gifts._ensure_workflow_visualizer_opt_in()

		set_value.assert_called_once_with(
			"Workflow",
			major_gifts.WORKFLOW_NAME,
			"visible_on_doctype",
			1,
			update_modified=False,
		)

	def test_workflow_visualizer_opt_in_skips_missing_field(self) -> None:
		workflow_meta = frappe._dict(has_field=lambda _fieldname: False)
		with (
			patch.object(frappe, "get_meta", return_value=workflow_meta),
			patch.object(frappe.db, "get_value") as get_value,
			patch.object(frappe.db, "set_value") as set_value,
		):
			major_gifts._ensure_workflow_visualizer_opt_in()

		get_value.assert_not_called()
		set_value.assert_not_called()
