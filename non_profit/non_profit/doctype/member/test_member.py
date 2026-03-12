import frappe
from frappe.tests import IntegrationTestCase


class TestMember(IntegrationTestCase):
    def test_member_requires_customer(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Member"}).insert()

    def test_company_customer_uses_organization_name(self):
        customer = self.create_customer("Company")
        self.create_contact(
            customer.name, "Alex", "Representative", is_primary_contact=1
        )

        member = frappe.get_doc(
            {"doctype": "Member", "customer": customer.name}
        ).insert()

        self.assertEqual(member.member_name, customer.customer_name)

    def test_individual_customer_uses_designated_representative_name(self):
        customer = self.create_customer("Individual")
        self.create_contact(customer.name, "Primary", "Person", is_primary_contact=1)
        representative = self.create_contact(customer.name, "Chosen", "Representative")

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "customer": customer.name,
                "designated_representative": representative.name,
            }
        ).insert()

        self.assertEqual(member.member_name, "Chosen Representative")

    def test_individual_customer_falls_back_to_primary_contact(self):
        customer = self.create_customer("Individual")
        self.create_contact(customer.name, "Jane", "Smith", is_primary_contact=1)

        member = frappe.get_doc(
            {"doctype": "Member", "customer": customer.name}
        ).insert()

        self.assertEqual(member.member_name, "Jane Smith")

    def test_individual_customer_falls_back_to_customer_name_without_contact(self):
        customer = self.create_customer("Individual")

        member = frappe.get_doc(
            {"doctype": "Member", "customer": customer.name}
        ).insert()

        self.assertEqual(member.member_name, customer.customer_name)

    def test_designated_representative_must_belong_to_same_customer(self):
        customer = self.create_customer("Individual")
        other_customer = self.create_customer("Individual")
        other_contact = self.create_contact(other_customer.name, "Other", "Customer")

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Member",
                    "customer": customer.name,
                    "designated_representative": other_contact.name,
                }
            ).insert()

    def test_duplicate_member_for_same_customer_is_rejected(self):
        customer = self.create_customer("Individual")

        frappe.get_doc({"doctype": "Member", "customer": customer.name}).insert()

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Member", "customer": customer.name}).insert()

    def test_get_contact_details_returns_resolved_contact(self):
        customer = self.create_customer("Individual")
        representative = self.create_contact(
            customer.name, "Jane", "Doe", is_primary_contact=1
        )
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "customer": customer.name,
                "designated_representative": representative.name,
            }
        ).insert()

        details = member.get_contact_details()

        self.assertEqual(details["resolved_contact"], representative.name)
        self.assertEqual(details["member_name"], "Jane Doe")
        self.assertTrue(details["has_contact"])

    def create_customer(self, customer_type):
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"_Test Member {customer_type} {frappe.generate_hash(length=8)}",
                "customer_type": customer_type,
                "customer_group": frappe.db.get_single_value(
                    "Selling Settings", "customer_group"
                ),
                "territory": frappe.db.get_single_value(
                    "Selling Settings", "territory"
                ),
            }
        ).insert()
        return customer

    def create_contact(
        self, customer_name, first_name, last_name, is_primary_contact=0, email=None
    ):
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": first_name,
                "last_name": last_name,
                "is_primary_contact": is_primary_contact,
                "email_ids": [
                    {
                        "doctype": "Contact Email",
                        "email_id": email
                        or f"{frappe.generate_hash(length=8)}@example.com",
                        "is_primary": 1,
                    }
                ],
                "links": [
                    {
                        "doctype": "Dynamic Link",
                        "link_doctype": "Customer",
                        "link_name": customer_name,
                    }
                ],
            }
        ).insert()
        return contact
