# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestGrantApplication(FrappeTestCase):
    def test_create_grant_application(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Grant Application",
                "applicant_type": "Organization",
                "applicant_name": f"Test Org {frappe.generate_hash(length=6)}",
                "email": f"test.grant.{frappe.generate_hash(length=8)}@example.com",
                "grant_description": "Test grant description",
                "amount": 1000,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Grant Application", doc.name))

    def test_route_is_auto_set_on_validate(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Grant Application",
                "applicant_type": "Individual",
                "applicant_name": f"Route Test Person {frappe.generate_hash(length=6)}",
                "email": f"test.grant.route.{frappe.generate_hash(length=8)}@example.com",
                "grant_description": "Route test description",
                "amount": 500,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(doc.route)
        self.assertTrue(doc.route.startswith("grant-application/"))

    def test_create_and_delete_grant_application(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Grant Application",
                "applicant_type": "Organization",
                "applicant_name": f"Delete Test Org {frappe.generate_hash(length=6)}",
                "email": f"test.grant.del.{frappe.generate_hash(length=8)}@example.com",
                "grant_description": "Delete test description",
                "amount": 2000,
            }
        ).insert(ignore_permissions=True)
        name = doc.name
        self.assertTrue(frappe.db.exists("Grant Application", name))
        doc.delete()
        self.assertFalse(frappe.db.exists("Grant Application", name))
