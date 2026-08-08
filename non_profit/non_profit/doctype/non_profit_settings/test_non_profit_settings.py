# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestNonProfitSettings(IntegrationTestCase):
	def test_load_non_profit_settings(self) -> None:
		doc = frappe.get_doc("Non Profit Settings")
		self.assertEqual(doc.doctype, "Non Profit Settings")

	def test_creditor_iban_is_the_optional_provider_override(self) -> None:
		meta = frappe.get_meta("Non Profit Settings")
		field = meta.get_field("creditor_iban")

		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Data")
		self.assertFalse(field.reqd)
		field_order = [docfield.fieldname for docfield in meta.fields]
		self.assertEqual(
			field_order.index("creditor_iban"),
			field_order.index("donation_company") + 1,
		)
		self.assertIn("before the Donation Company's default Bank Account", field.description)

	def test_save_non_profit_settings(self) -> None:
		doc = frappe.get_doc("Non Profit Settings")
		original = doc.send_email
		doc.send_email = 1
		doc.flags.ignore_permissions = True
		doc.save()
		doc.reload()
		self.assertEqual(doc.send_email, 1)
		doc.send_email = original
		doc.flags.ignore_permissions = True
		doc.save()
