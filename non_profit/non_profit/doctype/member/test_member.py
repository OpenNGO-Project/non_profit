# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe

from non_profit.non_profit.doctype.member.member import (
    create_member_and_membership,
    create_member,
    get_or_create_member_for_customer,
    get_or_create_membership_for_member,
    get_or_create_member,
    resolve_or_create_contact_from_external_signup,
)


class TestMember(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()

    def _membership_type(self) -> str:
        name = f"Identity Test {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Membership Type", "membership_type": name, "amount": 10}
        ).insert(ignore_permissions=True)
        return name

    def _customer(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"Member Customer {frappe.generate_hash(length=8)}"
        customer.customer_type = "Company"
        customer.customer_group = frappe.db.get_value(
            "Customer Group", {"is_group": 0}, "name"
        )
        customer.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
        customer.flags.ignore_mandatory = True
        customer.insert(ignore_permissions=True)
        return customer

    def test_get_or_create_member_uses_email_id_field(self):
        email = f"np-member-{frappe.generate_hash(length=8)}@example.org"
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "member_name": "Existing Member",
                "email_id": email,
            }
        ).insert(ignore_permissions=True)

        result = get_or_create_member(
            frappe._dict({"email": email, "membership_type": self._membership_type()})
        )

        self.assertEqual(result, member.name)

    def test_member_name_autofills_from_customer(self):
        customer = self._customer()

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "customer": customer.name,
            }
        ).insert(ignore_permissions=True)

        self.assertEqual(member.member_name, customer.customer_name)

    def test_customer_member_helper_creates_open_ended_membership(self):
        membership_type = self._membership_type()
        customer = self._customer()

        member = get_or_create_member_for_customer(
            customer.name,
            membership_type,
            ignore_permissions=True,
        )
        membership = get_or_create_membership_for_member(
            member.name,
            membership_type=membership_type,
            ignore_permissions=True,
        )

        self.assertEqual(member.customer, customer.name)
        self.assertFalse(membership.to_date)
        self.assertEqual(membership.membership_type, membership_type)

    def test_contact_member_helper_creates_standalone_member_and_membership(self):
        membership_type = self._membership_type()
        email = f"np-contact-member-{frappe.generate_hash(length=8)}@example.org"
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Standalone",
                "last_name": "Member",
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)

        result = create_member_and_membership(
            contact=contact.name,
            membership_type=membership_type,
        )

        member = frappe.get_doc("Member", result["member"])
        membership = frappe.get_doc("Membership", result["membership"])
        self.assertFalse(member.customer)
        self.assertEqual(member.email_id, email)
        self.assertEqual(membership.member, member.name)
        self.assertEqual(membership.membership_type, membership_type)
        self.assertFalse(membership.to_date)
        self.assertTrue(
            frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "parent": contact.name,
                    "link_doctype": "Member",
                    "link_name": member.name,
                },
            )
        )

    def test_customer_dialog_helper_creates_member_and_membership(self):
        membership_type = self._membership_type()
        customer = self._customer()

        result = create_member_and_membership(
            customer=customer.name,
            membership_type=membership_type,
        )

        member = frappe.get_doc("Member", result["member"])
        membership = frappe.get_doc("Membership", result["membership"])
        self.assertEqual(member.customer, customer.name)
        self.assertEqual(membership.member, member.name)
        self.assertEqual(membership.membership_type, membership_type)

    def test_member_pan_details_removed_from_schema(self):
        self.assertFalse(frappe.db.exists("Custom Field", "Member-pan_number"))
        self.assertFalse(frappe.db.has_column("Member", "pan_number"))
        for fieldname in ("company_80g_number", "with_effect_from", "pan_details"):
            self.assertFalse(frappe.db.has_column("Company", fieldname))
            self.assertFalse(frappe.db.exists("Custom Field", f"Company-{fieldname}"))
        self.assertFalse(frappe.db.exists("DocType", "Tax Exemption 80G Certificate"))
        self.assertFalse(
            frappe.db.exists("DocType", "Tax Exemption 80G Certificate Detail")
        )
        self.assertFalse(
            frappe.db.exists("Print Format", "80G Certificate for Donation")
        )
        self.assertFalse(
            frappe.db.exists("Print Format", "80G Certificate for Membership")
        )

    def test_member_membership_type_removed_from_schema(self):
        self.assertFalse(frappe.get_meta("Member").has_field("membership_type"))
        self.assertFalse(frappe.db.has_column("Member", "membership_type"))

    def test_member_dashboard_has_single_membership_link(self):
        dashboard = frappe.get_meta("Member").get_dashboard_data()
        transaction_items = [
            item for group in dashboard.transactions for item in group.get("items", [])
        ]

        self.assertEqual(transaction_items.count("Membership"), 1)
        self.assertNotIn("Bank Account", transaction_items)
        self.assertEqual(dashboard.transactions[0].get("label"), "Membership Details")
        self.assertEqual(dashboard.non_standard_fieldnames.get("Membership"), "member")
        self.assertNotIn("Bank Account", dashboard.non_standard_fieldnames)

    def test_create_member_reuses_exact_good_connector_contact(self):
        if not resolve_or_create_contact_from_external_signup:
            self.skipTest("good_connector identity matching is not installed")

        membership_type = self._membership_type()
        email = f"np-contact-{frappe.generate_hash(length=8)}@example.org"
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Legacy",
                "last_name": "Tester",
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)

        member = create_member(
            frappe._dict(
                {
                    "fullname": "Legacy Tester",
                    "email": email,
                    "membership_type": membership_type,
                    "pan": None,
                    "mobile": "+41 79 555 12 34",
                }
            )
        )

        self.assertEqual(frappe.db.count("Contact Email", {"email_id": email}), 1)
        self.assertTrue(member.customer)
        self.assertTrue(
            frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "parent": contact.name,
                    "link_doctype": "Member",
                    "link_name": member.name,
                },
            )
        )
        self.assertTrue(
            frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "parent": contact.name,
                    "link_doctype": "Customer",
                    "link_name": member.customer,
                },
            )
        )
