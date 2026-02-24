# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestDonor(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_donor_requires_customer(self):
        contact = self.create_test_contact()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor No Customer"
        donor.donor_type = donor_type
        donor.contact = contact.name
        donor.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            donor.save()

    def test_donor_requires_contact(self):
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor No Contact"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            donor.save()

    def test_donor_requires_donor_type(self):
        contact = self.create_test_contact()
        customer = self.create_test_customer()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor No Type"
        donor.contact = contact.name
        donor.customer = customer.name
        donor.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            donor.save()

    def test_donor_fetches_email_from_contact(self):
        contact = self.create_test_contact(email="donor@example.com")
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor Email"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        self.assertEqual(donor.email, "donor@example.com")

    def test_donor_fetches_phone_from_contact(self):
        contact = self.create_test_contact(phone="+1234567890")
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor Phone"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        self.assertEqual(donor.phone, "+1234567890")

    def test_contact_has_dynamic_link_to_donor(self):
        contact = self.create_test_contact()
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor DL"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        link_exists = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Donor",
                "link_name": donor.name,
            },
        )
        self.assertTrue(link_exists)

    def test_contact_has_dynamic_link_to_customer(self):
        contact = self.create_test_contact()
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor Customer DL"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        link_exists = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Customer",
                "link_name": customer.name,
            },
        )
        self.assertTrue(link_exists)

    def test_no_duplicate_dynamic_links_on_save(self):
        contact = self.create_test_contact()
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor Dup"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        donor.donor_name = "_Test Donor Dup Updated"
        donor.save()

        links = frappe.get_all(
            "Dynamic Link",
            filters={
                "parent": contact.name,
                "parenttype": "Contact",
                "link_doctype": "Donor",
                "link_name": donor.name,
            },
        )

        self.assertEqual(len(links), 1)

    def test_can_query_contacts_for_donor(self):
        contact = self.create_test_contact()
        customer = self.create_test_customer()
        donor_type = self.get_or_create_donor_type()

        donor = frappe.new_doc("Donor")
        donor.donor_name = "_Test Donor Query"
        donor.donor_type = donor_type
        donor.customer = customer.name
        donor.contact = contact.name
        donor.insert()

        contacts = frappe.get_all(
            "Contact",
            filters=[
                ["Dynamic Link", "link_doctype", "=", "Donor"],
                ["Dynamic Link", "link_name", "=", donor.name],
                ["Dynamic Link", "parenttype", "=", "Contact"],
            ],
            fields=["name"],
        )

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].name, contact.name)

    def test_create_donor_with_contact_and_customer(self):
        from non_profit.non_profit.doctype.donor.donor import (
            create_donor_with_contact_and_customer,
        )

        donor_type = self.get_or_create_donor_type()
        donor = create_donor_with_contact_and_customer(
            email="newdonor@example.com",
            donor_type=donor_type,
            donor_name="New Test Donor",
        )

        self.assertTrue(donor.name)
        self.assertEqual(donor.email, "newdonor@example.com")
        self.assertTrue(donor.contact)
        self.assertTrue(donor.customer)

        contact = frappe.get_doc("Contact", donor.contact)
        has_donor_link = any(
            l.link_doctype == "Donor" and l.link_name == donor.name
            for l in contact.links
        )
        has_customer_link = any(
            l.link_doctype == "Customer" and l.link_name == donor.customer
            for l in contact.links
        )
        self.assertTrue(has_donor_link)
        self.assertTrue(has_customer_link)

    def test_get_or_create_donor_returns_existing(self):
        from non_profit.non_profit.doctype.donor.donor import get_or_create_donor

        donor_type = self.get_or_create_donor_type()
        original = create_donor_with_contact_and_customer(
            email="existing@example.com",
            donor_type=donor_type,
        )

        found = get_or_create_donor("existing@example.com", donor_type)

        self.assertEqual(found.name, original.name)

    def create_test_contact(self, email=None, phone=None):
        contact = frappe.new_doc("Contact")
        contact.first_name = frappe.generate_hash("_Test Contact", 10)
        if email:
            contact.add_email(email, is_primary=1)
        if phone:
            contact.add_phone(phone, is_primary_phone=1, is_primary_mobile_no=1)
        contact.insert()
        return contact

    def create_test_customer(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = frappe.generate_hash("_Test Customer", 10)
        customer.customer_type = "Individual"
        customer.insert()
        return customer

    def get_or_create_donor_type(self):
        donor_type = frappe.db.exists("Donor Type", "_Test Donor Type")
        if donor_type:
            return donor_type

        dt = frappe.new_doc("Donor Type")
        dt.name = "_Test Donor Type"
        dt.donor_type = "_Test Donor Type"
        dt.insert()
        return dt.name


from non_profit.non_profit.doctype.donor.donor import (
    create_donor_with_contact_and_customer,
)
