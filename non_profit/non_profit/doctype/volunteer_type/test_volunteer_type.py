# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestVolunteerType(FrappeTestCase):
	def test_create_volunteer_type(self) -> None:
		name = f"Test Volunteer Type {frappe.generate_hash(length=6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Volunteer Type",
				"name": name,
				"volunteer_type": name,
				"amount": 100,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Volunteer Type", doc.name))

	def test_create_and_delete_volunteer_type(self) -> None:
		name = f"Delete Test VType {frappe.generate_hash(length=6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Volunteer Type",
				"name": name,
				"volunteer_type": name,
				"amount": 50,
			}
		).insert(ignore_permissions=True)
		name = doc.name
		self.assertTrue(frappe.db.exists("Volunteer Type", name))
		doc.delete()
		self.assertFalse(frappe.db.exists("Volunteer Type", name))
