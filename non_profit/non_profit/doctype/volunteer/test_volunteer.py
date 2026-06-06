# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

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

    def test_create_volunteer_from_contact_links_contact_without_customer(self) -> None:
        from non_profit.non_profit.doctype.volunteer.volunteer import create_volunteer_from_contact

        volunteer_type = self._make_volunteer_type()
        email = f"test.contact.volunteer.{frappe.generate_hash(length=8)}@example.com"
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Volunteer",
                "last_name": "Contact",
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)

        result = create_volunteer_from_contact(contact=contact.name, volunteer_type=volunteer_type)

        volunteer = frappe.get_doc("Volunteer", result["volunteer"])
        self.assertEqual(volunteer.email, email)
        self.assertTrue(
            frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "parent": contact.name,
                    "link_doctype": "Volunteer",
                    "link_name": volunteer.name,
                },
            )
        )
        self.assertFalse(
            frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "parent": contact.name,
                    "link_doctype": "Customer",
                },
            )
        )

    def test_create_volunteer_from_contact_requires_create_permission(self) -> None:
        from non_profit.non_profit.doctype.volunteer.volunteer import create_volunteer_from_contact

        volunteer_type = self._make_volunteer_type()
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Volunteer",
                "last_name": "Permission",
                "email_ids": [
                    {"email_id": f"volunteer.permission.{frappe.generate_hash(length=8)}@example.com"}
                ],
            }
        ).insert(ignore_permissions=True)

        with patch(
            "non_profit.non_profit.doctype.volunteer.volunteer.frappe.has_permission",
            side_effect=frappe.PermissionError,
        ):
            with self.assertRaises(frappe.PermissionError):
                create_volunteer_from_contact(contact=contact.name, volunteer_type=volunteer_type)

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
