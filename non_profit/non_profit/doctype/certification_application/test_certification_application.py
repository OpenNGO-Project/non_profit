# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCertificationApplication(FrappeTestCase):
    def test_create_certification_application(self) -> None:
        email = f"test.cert.app.{frappe.generate_hash(length=8)}@example.com"
        _ensure_test_user(email)
        doc = frappe.get_doc(
            {
                "doctype": "Certification Application",
                "name_of_applicant": f"Test Applicant {frappe.generate_hash(length=6)}",
                "email": email,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Certification Application", doc.name))

    def test_create_and_delete_certification_application(self) -> None:
        email = f"test.cert.delete.{frappe.generate_hash(length=8)}@example.com"
        _ensure_test_user(email)
        doc = frappe.get_doc(
            {
                "doctype": "Certification Application",
                "name_of_applicant": f"Delete Test Applicant {frappe.generate_hash(length=6)}",
                "email": email,
            }
        ).insert(ignore_permissions=True)
        name = doc.name
        self.assertTrue(frappe.db.exists("Certification Application", name))
        doc.delete()
        self.assertFalse(frappe.db.exists("Certification Application", name))


def _ensure_test_user(email: str) -> str:
    if frappe.db.exists("User", email):
        return email
    frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": email.split("@", 1)[0],
            "send_welcome_email": 0,
            "enabled": 1,
        }
    ).insert(ignore_permissions=True)
    return email
