# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe

from non_profit.non_profit.doctype.member.member import (
    create_member,
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
        frappe.get_doc({"doctype": "Membership Type", "membership_type": name, "amount": 10}).insert(
            ignore_permissions=True
        )
        return name

    def test_get_or_create_member_uses_email_id_field(self):
        membership_type = self._membership_type()
        email = f"np-member-{frappe.generate_hash(length=8)}@example.org"
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "member_name": "Existing Member",
                "membership_type": membership_type,
                "email_id": email,
            }
        ).insert(ignore_permissions=True)

        result = get_or_create_member(
            frappe._dict({"email": email, "plan_id": membership_type})
        )

        self.assertEqual(result, member.name)

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
                    "plan_id": membership_type,
                    "pan": None,
                    "customer_id": None,
                    "subscription_id": None,
                    "subscription_status": "",
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
