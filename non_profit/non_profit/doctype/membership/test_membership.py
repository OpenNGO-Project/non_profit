import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

import erpnext
from non_profit.non_profit.doctype.member.member import (
    create_member,
    get_member_contact,
)


class TestMembership(IntegrationTestCase):
    def setUp(self):
        plan = setup_membership()
        self.plan = plan
        unique = frappe.generate_hash(length=8)
        self.member_doc = create_member(
            frappe._dict(
                {
                    "fullname": f"_Test_Member_{unique}",
                    "email": f"_test_member_{unique}@example.com",
                }
            )
        )
        self.member = self.member_doc.name
        self.customer = self.member_doc.customer

    def test_create_membership(self):
        membership = make_membership(self.member)
        self.assertTrue(membership.name)
        self.assertEqual(membership.customer, self.customer)
        self.assertEqual(membership.contact, get_member_contact(self.member).name)

    def test_membership_uses_member_customer_for_subscription_party(self):
        membership = make_membership(self.member)
        membership.submit()

        subscription = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(subscription.party, self.customer)

    def test_membership_creates_subscription(self):
        membership = make_membership(self.member)
        membership.submit()

        self.assertTrue(membership.subscription)

        sub = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(sub.party, self.customer)

    def test_gift_membership_can_use_different_billing_customer_and_contact(self):
        billing_customer = create_customer_with_contact()

        membership = make_membership(
            self.member,
            {
                "customer": billing_customer["customer"].name,
                "contact": billing_customer["contact"].name,
            },
        )
        membership.submit()

        sub = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(membership.customer, billing_customer["customer"].name)
        self.assertEqual(membership.contact, billing_customer["contact"].name)
        self.assertEqual(sub.party, billing_customer["customer"].name)

    def test_billing_contact_must_match_billing_customer(self):
        billing_customer = create_customer_with_contact()
        other_billing_customer = create_customer_with_contact()

        with self.assertRaises(frappe.ValidationError):
            make_membership(
                self.member,
                {
                    "customer": billing_customer["customer"].name,
                    "contact": other_billing_customer["contact"].name,
                },
            )

    def test_member_can_have_multiple_active_memberships(self):
        """Test that a member can have multiple active memberships of different types."""
        membership1 = make_membership(self.member)
        membership1.submit()

        self.assertTrue(membership1.subscription)

        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": self.member, "docstatus": 1},
        )
        self.assertEqual(len(active_memberships), 1)

    def test_duplicate_membership_type_not_allowed(self):
        """Test that duplicate membership of same type is not allowed."""
        membership1 = make_membership(self.member)
        membership1.submit()

        membership2_data = {
            "doctype": "Membership",
            "member": self.member,
            "membership_type": "_rzpy_test_milythm",
            "company": erpnext.get_default_company(),
            "member_since_date": nowdate(),
            "auto_renew": 1,
        }
        membership2 = frappe.get_doc(membership2_data)

        with self.assertRaises(frappe.ValidationError):
            membership2.insert(ignore_permissions=True)

    def test_membership_cancel_cancels_subscription(self):
        """Test that cancelling membership cancels the subscription."""
        membership = make_membership(self.member)
        membership.submit()

        self.assertTrue(membership.subscription)

        membership.cancel()

        sub = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(sub.status, "Cancelled")

    def test_get_active_memberships(self):
        """Test getting active memberships from member."""
        membership = make_membership(self.member)
        membership.submit()

        active = self.member_doc.get_active_memberships()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["name"], membership.name)

    def test_get_primary_membership(self):
        """Test getting primary (most recent) membership from member."""
        membership = make_membership(self.member)
        membership.submit()

        primary = self.member_doc.get_primary_membership()
        self.assertIsNotNone(primary)
        self.assertEqual(primary["name"], membership.name)


def make_membership(member, payload={}):
    data = {
        "doctype": "Membership",
        "member": member,
        "membership_type": "_rzpy_test_milythm",
        "company": erpnext.get_default_company(),
        "member_since_date": nowdate(),
        "auto_renew": 1,
    }
    data.update(payload)
    membership = frappe.get_doc(data)
    membership.insert(ignore_permissions=True)
    return membership


def create_item(item_code):
    if not frappe.db.exists("Item", item_code):
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_code
        item.stock_uom = "Nos"
        item.description = item_code
        item.item_group = "All Item Groups"
        item.is_stock_item = 0
        item.save()
    else:
        item = frappe.get_doc("Item", item_code)
    return item


def setup_membership():
    company = frappe.get_doc("Company", erpnext.get_default_company())

    settings = frappe.get_doc("Non Profit Settings")
    settings.company = company.name
    settings.flags.ignore_mandatory = True
    settings.save()

    if not frappe.db.exists("Membership Type", "_rzpy_test_milythm"):
        plan = frappe.new_doc("Membership Type")
        plan.membership_type = "_rzpy_test_milythm"
        plan.amount = 100
        plan.linked_item = create_item("_Test Item for Non Profit Membership").name
        plan.auto_create_subscription_plan = 1
        plan.insert()
    else:
        plan = frappe.get_doc("Membership Type", "_rzpy_test_milythm")

    return plan


def create_customer_with_contact():
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": f"_Test Billing {frappe.generate_hash(length=8)}",
            "customer_type": "Individual",
            "customer_group": frappe.db.get_single_value(
                "Selling Settings", "customer_group"
            ),
            "territory": frappe.db.get_single_value("Selling Settings", "territory"),
        }
    ).insert()

    contact = frappe.get_doc(
        {
            "doctype": "Contact",
            "first_name": "Billing",
            "last_name": frappe.generate_hash(length=6),
            "is_primary_contact": 1,
            "email_ids": [
                {
                    "doctype": "Contact Email",
                    "email_id": f"{frappe.generate_hash(length=8)}@example.com",
                    "is_primary": 1,
                }
            ],
            "links": [
                {
                    "doctype": "Dynamic Link",
                    "link_doctype": "Customer",
                    "link_name": customer.name,
                }
            ],
        }
    ).insert()

    return {"customer": customer, "contact": contact}
