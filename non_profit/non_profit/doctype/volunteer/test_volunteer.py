# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestVolunteer(FrappeTestCase):
    def test_create_volunteer(self) -> None:
        volunteer_type = self._make_volunteer_type()
        doc = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test Volunteer {frappe.generate_hash(length=6)}",
                "volunteer_type": volunteer_type,
                "email": f"test.volunteer.{frappe.generate_hash(length=8)}@example.com",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Volunteer", doc.name))
        self.assertEqual(doc.email, doc.name)

    def test_volunteer_onload_does_not_error(self) -> None:
        volunteer_type = self._make_volunteer_type()
        doc = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Onload Test Volunteer {frappe.generate_hash(length=6)}",
                "volunteer_type": volunteer_type,
                "email": f"test.onload.volunteer.{frappe.generate_hash(length=8)}@example.com",
            }
        ).insert(ignore_permissions=True)
        loaded = frappe.get_doc("Volunteer", doc.name)
        loaded.onload()
        self.assertTrue(loaded.as_dict().get("__onload") is not None)

    def _make_volunteer_type(self) -> str:
        name = f"Test VType {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Volunteer Type",
                "name": name,
                "volunteer_type": name,
                "amount": 0,
            }
        ).insert(ignore_permissions=True)
        return name
