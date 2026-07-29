from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from non_profit import hooks as non_profit_hooks
from non_profit import setup as non_profit_setup
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

	def test_visualizer_installed_after_non_profit_opts_in_major_gift_workflow(self) -> None:
		if not frappe.get_meta("Workflow").has_field("visible_on_doctype"):
			self.skipTest("workflow_visualizer is not installed")
		self.assertEqual(non_profit_hooks.after_app_install, "non_profit.setup.after_app_install")

		from non_profit.non_profit.major_gifts import (
			WORKFLOW_NAME,
			WORKFLOW_ROLES,
			WORKFLOW_VERSION_KEY,
			_workflow_definition_hash,
		)

		edit_role = next(role for role in WORKFLOW_ROLES if frappe.db.exists("Role", role))
		frappe.db.set_default(WORKFLOW_VERSION_KEY, _workflow_definition_hash(edit_role))
		frappe.db.set_value(
			"Workflow",
			WORKFLOW_NAME,
			{"visible_on_doctype": 0, "send_email_alert": 1},
			update_modified=False,
		)

		non_profit_setup.after_app_install("workflow_visualizer")

		workflow_values = frappe.db.get_value(
			"Workflow", WORKFLOW_NAME, ["visible_on_doctype", "send_email_alert"], as_dict=True
		)
		self.assertTrue(workflow_values.visible_on_doctype)
		self.assertTrue(workflow_values.send_email_alert)
