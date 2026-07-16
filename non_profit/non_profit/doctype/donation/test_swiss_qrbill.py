import frappe
from frappe.tests.utils import FrappeTestCase


class TestSwissQRBill(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_resolve_creditor_returns_none_without_iban(self) -> None:
		if not frappe.db.exists("DocType", "Non Profit Settings"):
			self.skipTest("Non Profit Settings DocType not found")
		from non_profit.non_profit.swiss_qrbill import _resolve_creditor

		settings = frappe.get_doc("Non Profit Settings")
		if hasattr(settings, "creditor_iban"):
			settings.creditor_iban = ""
			settings.flags.ignore_permissions = True
			settings.save()

		iban, creditor = _resolve_creditor()
		self.assertIsNone(iban)
		self.assertIsNone(creditor)

	def test_no_creditor_returns_error_html(self) -> None:
		if not frappe.db.exists("DocType", "Non Profit Settings"):
			self.skipTest("Non Profit Settings DocType not found")
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		settings = frappe.get_doc("Non Profit Settings")
		if hasattr(settings, "creditor_iban"):
			settings.creditor_iban = ""
			settings.flags.ignore_permissions = True
			settings.save()

		doc = frappe._dict(amount=50, name="DON-TEST-001")
		result = swiss_qrbill_svg(doc)
		self.assertIn("not configured", result)
		self.assertIn("<p", result)

	def test_with_creditor_returns_svg_or_error(self) -> None:
		if not frappe.db.exists("DocType", "Non Profit Settings"):
			self.skipTest("Non Profit Settings DocType not found")
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		settings = frappe.get_doc("Non Profit Settings")
		if not hasattr(settings, "creditor_iban"):
			self.skipTest("creditor_iban field not on Non Profit Settings")
		settings.creditor_iban = "CH44 3199 9123 0008 8901 2"
		settings.creditor_name = "Test NGO"
		settings.creditor_address_line1 = "Bahnhofstrasse 1"
		settings.creditor_address_line2 = "8001 Zurich"
		settings.flags.ignore_permissions = True
		settings.save()

		doc = frappe._dict(amount=50, name="DON-TEST-002")
		result = swiss_qrbill_svg(doc)
		self.assertIsInstance(result, str)
		self.assertTrue(len(result) > 0)
