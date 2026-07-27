# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json
import unittest
from unittest.mock import patch

import frappe

from non_profit.non_profit.doctype.member.member import (
	create_member,
	create_member_and_membership,
	get_or_create_member,
	get_or_create_member_for_contact,
	get_or_create_member_for_customer,
	get_or_create_membership_for_member,
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

	def _customer(self):
		customer = frappe.new_doc("Customer")
		customer.customer_name = f"Member Customer {frappe.generate_hash(length=8)}"
		customer.customer_type = "Company"
		customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
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
		if customer.meta.has_field("name_additional"):
			customer.name_additional = "Additional Line"
			customer.save(ignore_permissions=True)

		member = frappe.get_doc(
			{
				"doctype": "Member",
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)

		expected_name = (
			f"{customer.customer_name} - Additional Line"
			if customer.meta.has_field("name_additional")
			else customer.customer_name
		)
		self.assertEqual(member.member_name, expected_name)

	def test_member_name_preserves_manual_value_with_customer(self):
		customer = self._customer()
		member = frappe.get_doc(
			{
				"doctype": "Member",
				"customer": customer.name,
				"member_name": "Manual Membership Display Name",
			}
		).insert(ignore_permissions=True)

		self.assertEqual(member.member_name, "Manual Membership Display Name")

	def test_member_name_is_required_without_customer_or_programmatic_name(self):
		member = frappe.new_doc("Member")

		with self.assertRaises(frappe.ValidationError):
			member.insert(ignore_permissions=True)

	def test_member_form_layout_keeps_customer_next_to_member_name(self):
		with open(
			frappe.get_app_path("non_profit", "non_profit", "doctype", "member", "member.json")
		) as handle:
			member_meta = json.load(handle)

		self.assertEqual(
			member_meta["field_order"][:6],
			["naming_series", "member_name", "subject_type", "contact", "column_break_5", "customer"],
		)
		fieldnames = {field["fieldname"] for field in member_meta["fields"]}
		self.assertNotIn("customer_section", fieldnames)
		self.assertNotIn("customer_name", fieldnames)

		member_name_field = next(
			field for field in member_meta["fields"] if field["fieldname"] == "member_name"
		)
		self.assertFalse(member_name_field.get("read_only"))

	def test_member_expiry_client_sync_does_not_mark_form_dirty(self):
		with open(
			frappe.get_app_path("non_profit", "non_profit", "doctype", "member", "member.js")
		) as handle:
			member_script = handle.read()

		self.assertIn('frappe.meta.has_field(frm.doctype, "membership_expiry_date")', member_script)
		self.assertIn('"membership_expiry_date",', member_script)
		self.assertIn("null,\n\t\t\t\ttrue", member_script)

	def test_member_list_uses_native_creation_dialog_action(self):
		with open(
			frappe.get_app_path("non_profit", "non_profit", "doctype", "member", "member_list.js")
		) as handle:
			member_list_script = handle.read()
		with open(
			frappe.get_app_path("non_profit", "non_profit", "doctype", "member", "member.js")
		) as handle:
			member_form_script = handle.read()

		self.assertIn("primary_action()", member_list_script)
		self.assertIn("show_member_creation_dialog();", member_list_script)
		self.assertNotIn("show_member_creation_dialog", member_form_script)
		self.assertNotIn("__member_creation_dialog_shown", member_form_script)

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
		self.assertIsNone(result["customer"])
		self.assertFalse(member.customer)
		self.assertEqual(member.email_id, email)
		self.assertEqual(member.subject_type, "Individual")
		self.assertEqual(member.contact, contact.name)
		self.assertEqual(frappe.db.get_value("Contact", contact.name, "npo_identity_kind"), "Person")
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
		self.assertFalse(
			frappe.db.exists(
				"Dynamic Link",
				{"parenttype": "Contact", "parent": contact.name, "link_doctype": "Customer"},
			)
		)

	def test_contact_member_helper_rejects_generic_endpoint(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Shared Mailbox",
				"npo_identity_kind": "Generic Endpoint",
				"email_ids": [
					{
						"email_id": f"np-generic-contact-{frappe.generate_hash(length=8)}@example.org",
						"is_primary": 1,
					}
				],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			get_or_create_member_for_contact(contact.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Member", {"contact": contact.name}))

	def test_canonical_contact_cannot_be_retargeted_by_saving_member(self):
		first_contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "First Canonical Member Contact"}
		).insert(ignore_permissions=True)
		second_contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Second Canonical Member Contact"}
		).insert(ignore_permissions=True)
		member = frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": "Canonical Contact Member",
				"contact": first_contact.name,
			}
		).insert(ignore_permissions=True)

		member.contact = second_contact.name
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be changed directly"):
			member.save(ignore_permissions=True)

	def test_canonical_contact_cannot_be_added_by_saving_existing_member(self):
		member = frappe.get_doc(
			{"doctype": "Member", "member_name": "Existing Member Without Canonical Contact"}
		).insert(ignore_permissions=True)
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Later Canonical Member Contact"}
		).insert(ignore_permissions=True)

		member.contact = contact.name
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be changed directly"):
			member.save(ignore_permissions=True)

	def test_contact_cannot_be_canonical_for_two_members(self):
		from non_profit.non_profit.doctype.member.member import _link_contact_to_member

		contact = frappe.get_doc({"doctype": "Contact", "first_name": "One Canonical Member Role"}).insert(
			ignore_permissions=True
		)
		first_member = frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": "First Canonical Member Role",
				"contact": contact.name,
			}
		).insert(ignore_permissions=True)
		second_member = frappe.get_doc(
			{"doctype": "Member", "member_name": "Second Canonical Member Role"}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, first_member.name):
			_link_contact_to_member(contact.name, second_member.name, ignore_permissions=True)

	def test_legacy_member_contact_link_cannot_be_reclassified_as_generic_endpoint(self):
		member = frappe.get_doc({"doctype": "Member", "member_name": "Legacy Dynamic Link Member"}).insert(
			ignore_permissions=True
		)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Legacy Dynamic Link Member",
				"links": [{"link_doctype": "Member", "link_name": member.name}],
			}
		).insert(ignore_permissions=True)

		contact.npo_identity_kind = "Generic Endpoint"
		with self.assertRaisesRegex(frappe.ValidationError, "used as a person role"):
			contact.save(ignore_permissions=True)

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

	def test_create_member_and_membership_requires_create_permission(self):
		membership_type = self._membership_type()
		customer = self._customer()

		with patch(
			"non_profit.non_profit.doctype.member.member.frappe.has_permission",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				create_member_and_membership(customer=customer.name, membership_type=membership_type)

	def test_dialog_helper_accepts_contact_and_customer_together(self):
		membership_type = self._membership_type()
		customer = self._customer()
		email = f"np-contact-customer-member-{frappe.generate_hash(length=8)}@example.org"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Combined",
				"last_name": "Member",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		result = create_member_and_membership(
			contact=contact.name,
			customer=customer.name,
			membership_type=membership_type,
		)

		member = frappe.get_doc("Member", result["member"])
		self.assertEqual(member.customer, customer.name)
		self.assertEqual(member.subject_type, "Individual")
		self.assertEqual(member.contact, contact.name)
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

	def test_member_pan_details_removed_from_schema(self):
		self.assertFalse(frappe.db.exists("Custom Field", "Member-pan_number"))
		self.assertFalse(frappe.db.has_column("Member", "pan_number"))
		for fieldname in ("company_80g_number", "with_effect_from", "pan_details"):
			self.assertFalse(frappe.db.has_column("Company", fieldname))
			self.assertFalse(frappe.db.exists("Custom Field", f"Company-{fieldname}"))
		self.assertFalse(frappe.db.exists("DocType", "Tax Exemption 80G Certificate"))
		self.assertFalse(frappe.db.exists("DocType", "Tax Exemption 80G Certificate Detail"))
		self.assertFalse(frappe.db.exists("Print Format", "80G Certificate for Donation"))
		self.assertFalse(frappe.db.exists("Print Format", "80G Certificate for Membership"))

	def test_member_membership_type_removed_from_schema(self):
		self.assertFalse(frappe.get_meta("Member").has_field("membership_type"))
		self.assertFalse(frappe.db.has_column("Member", "membership_type"))

	def test_member_dashboard_has_single_membership_link(self):
		dashboard = frappe.get_meta("Member").get_dashboard_data()
		transaction_items = [item for group in dashboard.transactions for item in group.get("items", [])]

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
		self.assertEqual(member.subject_type, "Individual")
		self.assertEqual(member.contact, contact.name)
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
