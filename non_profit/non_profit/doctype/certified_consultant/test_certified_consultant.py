# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCertifiedConsultant(FrappeTestCase):
    def test_create_certified_consultant(self) -> None:
        application = self._make_application()
        doc = frappe.get_doc(
            {
                "doctype": "Certified Consultant",
                "name_of_consultant": f"Test Consultant {frappe.generate_hash(length=6)}",
                "country": "Switzerland",
                "certification_application": application,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Certified Consultant", doc.name))

    def test_create_and_delete_certified_consultant(self) -> None:
        application = self._make_application()
        doc = frappe.get_doc(
            {
                "doctype": "Certified Consultant",
                "name_of_consultant": f"Delete Test Consultant {frappe.generate_hash(length=6)}",
                "country": "Switzerland",
                "certification_application": application,
            }
        ).insert(ignore_permissions=True)
        name = doc.name
        self.assertTrue(frappe.db.exists("Certified Consultant", name))
        doc.delete()
        self.assertFalse(frappe.db.exists("Certified Consultant", name))

    def _make_application(self) -> str:
        doc = frappe.get_doc(
            {
                "doctype": "Certification Application",
                "name_of_applicant": f"Linked Applicant {frappe.generate_hash(length=6)}",
                "email": f"linked.app.{frappe.generate_hash(length=8)}@example.com",
            }
        ).insert(ignore_permissions=True)
        return doc.name
