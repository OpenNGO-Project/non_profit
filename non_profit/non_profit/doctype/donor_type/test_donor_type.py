# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestDonorType(IntegrationTestCase):
	def test_create_donor_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Donor Type",
				"donor_type": f"Test Donor Type {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Donor Type", doc.name))

	def test_create_and_delete_donor_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Donor Type",
				"donor_type": f"Delete Test Donor Type {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		name = doc.name
		self.assertTrue(frappe.db.exists("Donor Type", name))
		doc.delete()
		self.assertFalse(frappe.db.exists("Donor Type", name))
