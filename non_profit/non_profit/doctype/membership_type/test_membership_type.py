# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestMembershipType(IntegrationTestCase):
	def test_create_membership_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Membership Type",
				"membership_type": f"Test MType {frappe.generate_hash(length=6)}",
				"amount": 50,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Membership Type", doc.name))

	def test_create_with_non_stock_linked_item(self) -> None:
		item = self._make_service_item()
		doc = frappe.get_doc(
			{
				"doctype": "Membership Type",
				"membership_type": f"Test MType Item {frappe.generate_hash(length=6)}",
				"amount": 100,
				"linked_item": item,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Membership Type", doc.name))
		self.assertEqual(doc.linked_item, item)

	def test_stock_linked_item_is_rejected(self) -> None:
		item = self._make_stock_item()
		doc = frappe.get_doc(
			{
				"doctype": "Membership Type",
				"membership_type": f"Test MType Stock {frappe.generate_hash(length=6)}",
				"amount": 100,
				"linked_item": item,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_create_and_delete_membership_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Membership Type",
				"membership_type": f"Delete Test MType {frappe.generate_hash(length=6)}",
				"amount": 25,
			}
		).insert(ignore_permissions=True)
		name = doc.name
		self.assertTrue(frappe.db.exists("Membership Type", name))
		doc.delete()
		self.assertFalse(frappe.db.exists("Membership Type", name))

	def _make_service_item(self) -> str:
		name = f"Test Service Item {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": self._item_group(),
				"is_stock_item": 0,
				"stock_uom": "Nos",
			}
		).insert(ignore_permissions=True)
		return name

	def _make_stock_item(self) -> str:
		name = f"Test Stock Item {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": self._item_group(),
				"is_stock_item": 1,
				"stock_uom": "Nos",
			}
		).insert(ignore_permissions=True)
		return name

	def _item_group(self) -> str | None:
		return frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="name asc")
