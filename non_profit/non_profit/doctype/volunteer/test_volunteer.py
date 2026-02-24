# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestVolunteer(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_volunteer_requires_contact(self):
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer No Contact"
        volunteer.volunteer_type = volunteer_type
        volunteer.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            volunteer.save()

    def test_volunteer_requires_volunteer_type(self):
        contact = self.create_test_contact()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer No Type"
        volunteer.contact = contact.name
        volunteer.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            volunteer.save()

    def test_volunteer_fetches_email_from_contact(self):
        contact = self.create_test_contact(email="volunteer@example.com")
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer Email"
        volunteer.volunteer_type = volunteer_type
        volunteer.contact = contact.name
        volunteer.insert()

        self.assertEqual(volunteer.email, "volunteer@example.com")

    def test_contact_has_dynamic_link_to_volunteer(self):
        contact = self.create_test_contact()
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer DL"
        volunteer.volunteer_type = volunteer_type
        volunteer.contact = contact.name
        volunteer.insert()

        link_exists = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Volunteer",
                "link_name": volunteer.name,
            },
        )
        self.assertTrue(link_exists)

    def test_dynamic_link_has_correct_title(self):
        contact = self.create_test_contact()
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer Title"
        volunteer.volunteer_type = volunteer_type
        volunteer.contact = contact.name
        volunteer.insert()

        link = frappe.db.get_value(
            "Dynamic Link",
            {
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Volunteer",
                "link_name": volunteer.name,
            },
            "link_title",
        )
        self.assertEqual(link, "_Test Volunteer Title")

    def test_no_duplicate_dynamic_links_on_save(self):
        contact = self.create_test_contact()
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer Dup"
        volunteer.volunteer_type = volunteer_type
        volunteer.contact = contact.name
        volunteer.insert()

        volunteer.volunteer_name = "_Test Volunteer Dup Updated"
        volunteer.save()

        links = frappe.get_all(
            "Dynamic Link",
            filters={
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Volunteer",
                "link_name": volunteer.name,
            },
        )

        self.assertEqual(len(links), 1)

    def test_can_query_contacts_for_volunteer(self):
        contact = self.create_test_contact()
        volunteer_type = self.get_or_create_volunteer_type()

        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = "_Test Volunteer Query"
        volunteer.volunteer_type = volunteer_type
        volunteer.contact = contact.name
        volunteer.insert()

        contacts = frappe.get_all(
            "Contact",
            filters=[
                ["Dynamic Link", "link_doctype", "=", "Volunteer"],
                ["Dynamic Link", "link_name", "=", volunteer.name],
                ["Dynamic Link", "parenttype", "=", "Contact"],
            ],
            fields=["name"],
        )

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].name, contact.name)

    def create_test_contact(self, email=None):
        contact = frappe.new_doc("Contact")
        contact.first_name = frappe.generate_hash("_Test Contact", 10)
        if email:
            contact.add_email(email, is_primary=1)
        contact.insert()
        return contact

    def get_or_create_volunteer_type(self):
        volunteer_type = frappe.db.exists("Volunteer Type", "_Test Volunteer Type")
        if volunteer_type:
            return volunteer_type

        vt = frappe.new_doc("Volunteer Type")
        vt.name = "_Test Volunteer Type"
        vt.volunteer_type = "_Test Volunteer Type"
        vt.amount = 0
        vt.insert()
        return vt.name
