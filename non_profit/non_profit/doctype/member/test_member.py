import frappe
from frappe.tests.utils import FrappeTestCase


class TestMember(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_member_requires_customer(self):
        member = frappe.new_doc("Member")
        member.member_name = "_Test Member No Customer"
        member.email_id = "test_no_customer@example.com"
        member.membership_type = self.get_or_create_membership_type()
        member.flags.ignore_mandatory = True

        with self.assertRaises(frappe.ValidationError):
            member.save()

    def test_member_fetches_contact_details(self):
        customer = self.create_test_customer()
        contact = self.create_test_contact(customer, "John", "Doe")

        member = frappe.new_doc("Member")
        member.member_name = "_Test Member With Contact"
        member.email_id = "test_with_contact@example.com"
        member.membership_type = self.get_or_create_membership_type()
        member.customer = customer.name
        member.insert()

        self.assertEqual(member.first_name, "John")
        self.assertEqual(member.last_name, "Doe")

    def test_member_without_contact(self):
        customer = self.create_test_customer()

        member = frappe.new_doc("Member")
        member.member_name = "_Test Member No Contact"
        member.email_id = "test_no_contact@example.com"
        member.membership_type = self.get_or_create_membership_type()
        member.customer = customer.name
        member.insert()

        self.assertEqual(member.first_name, "")
        self.assertEqual(member.last_name, "")

    def test_get_contact_details_api(self):
        customer = self.create_test_customer()
        contact = self.create_test_contact(customer, "Jane", "Smith")

        member = frappe.new_doc("Member")
        member.member_name = "_Test Member API"
        member.email_id = "test_api@example.com"
        member.membership_type = self.get_or_create_membership_type()
        member.customer = customer.name
        member.insert()

        result = member.get_contact_details()

        self.assertEqual(result["first_name"], "Jane")
        self.assertEqual(result["last_name"], "Smith")
        self.assertTrue(result["has_contact"])

    def create_test_customer(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = frappe.generate_hash("_Test Customer", 10)
        customer.customer_type = "Individual"
        customer.insert()
        return customer

    def create_test_contact(self, customer, first_name, last_name):
        contact = frappe.new_doc("Contact")
        contact.first_name = first_name
        contact.last_name = last_name
        contact.is_primary_contact = 1
        contact.insert()
        contact.append(
            "links", {"link_doctype": "Customer", "link_name": customer.name}
        )
        contact.save()
        return contact

    def get_or_create_membership_type(self):
        membership_type_name = "_Test Member MType"
        if not frappe.db.exists("Membership Type", membership_type_name):
            if not frappe.db.exists("Item", "_Test Member Item"):
                item = frappe.new_doc("Item")
                item.item_code = "_Test Member Item"
                item.item_name = "_Test Member Item"
                item.stock_uom = "Nos"
                item.item_group = "All Item Groups"
                item.is_stock_item = 0
                item.insert()

            mtype = frappe.new_doc("Membership Type")
            mtype.membership_type = membership_type_name
            mtype.amount = 100
            mtype.linked_item = "_Test Member Item"
            mtype.insert()

        return membership_type_name

    def tearDown(self):
        frappe.db.rollback()
