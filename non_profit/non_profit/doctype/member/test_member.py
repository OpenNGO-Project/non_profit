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

	def _guided_person_values(self, **overrides) -> dict:
		if (
			not resolve_or_create_contact_from_external_signup
			or "good_connector" not in frappe.get_installed_apps()
		):
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		values = {
			"member_kind": "Individual",
			"membership_type": self._membership_type(),
			"from_date": "2026-07-01",
			"first_name": "Guided",
			"last_name": f"Member {unique}",
			"email": f"guided-member-{unique}@example.org",
			"phone": "+41 79 555 12 34",
			"address_line1": "Teststrasse 12",
			"postal_code": "8000",
			"city": "Zürich",
			"country": "Switzerland",
		}
		values.update(overrides)
		return values

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
		self.assertIn("create_member_and_membership", member_list_script)
		self.assertIn('type: "POST"', member_list_script)
		self.assertIn(".always(() => dialog.enable_primary_action())", member_list_script)
		self.assertIn('frappe.set_route("Form", "Member", result.member)', member_list_script)
		self.assertIn('fieldname: "existing_address"', member_list_script)
		self.assertIn('frappe.db.get_doc("Contact", contactName)', member_list_script)
		self.assertIn('frappe.db.get_doc("Address", addressName)', member_list_script)
		self.assertIn('dialog.set_df_property(fieldname, "read_only", readOnly)', member_list_script)
		self.assertIn("The selected Contact needs a primary email address.", member_list_script)
		self.assertNotIn("contact.email_ids?.[0]?.email_id", member_list_script)
		self.assertNotIn("show_member_creation_dialog", member_form_script)
		self.assertNotIn("__member_creation_dialog_shown", member_form_script)

	def test_guided_individual_creates_complete_current_membership_identity(self):
		values = self._guided_person_values()

		result = create_member_and_membership(**values)

		contact = frappe.get_doc("Contact", result["contact"])
		customer = frappe.get_doc("Customer", result["customer"])
		member = frappe.get_doc("Member", result["member"])
		membership = frappe.get_doc("Membership", result["membership"])
		address = frappe.get_doc("Address", result["address"])
		self.assertEqual(contact.npo_identity_kind, "Person")
		self.assertEqual(customer.customer_type, "Individual")
		self.assertEqual(customer.customer_primary_contact, contact.name)
		self.assertEqual(member.contact, contact.name)
		self.assertEqual(member.customer, customer.name)
		self.assertEqual(member.subject_type, "Individual")
		self.assertEqual(membership.member, member.name)
		self.assertEqual(membership.membership_status, "Current")
		self.assertEqual(str(membership.from_date), values["from_date"])
		self.assertFalse(membership.to_date)
		for link_doctype, link_name in (
			("Contact", contact.name),
			("Customer", customer.name),
			("Member", member.name),
		):
			self.assertTrue(
				any(row.link_doctype == link_doctype and row.link_name == link_name for row in address.links)
			)

	def test_guided_individual_uses_explicit_existing_contact_and_address(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Existing",
				"last_name": f"Person {unique}",
				"email_ids": [{"email_id": f"existing-person-{unique}@example.org", "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Existing Address {unique}",
				"address_type": "Billing",
				"address_line1": "Existing Street 8",
				"pincode": "3011",
				"city": "Bern",
				"country": "Switzerland",
			}
		).insert(ignore_permissions=True)

		result = create_member_and_membership(
			member_kind="Individual",
			contact=contact.name,
			existing_address=address.name,
			membership_type=self._membership_type(),
			from_date="2026-07-01",
		)

		self.assertEqual(result["contact"], contact.name)
		self.assertEqual(result["address"], address.name)
		address.reload()
		for link_doctype, link_name in (
			("Contact", contact.name),
			("Customer", result["customer"]),
			("Member", result["member"]),
		):
			self.assertTrue(
				any(row.link_doctype == link_doctype and row.link_name == link_name for row in address.links)
			)

	def test_guided_existing_contact_requires_primary_email(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "No Primary",
				"last_name": f"Email {unique}",
			}
		).insert(ignore_permissions=True)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"No Primary Email {unique}",
				"address_type": "Billing",
				"address_line1": "Email Street 3",
				"pincode": "4001",
				"city": "Basel",
				"country": "Switzerland",
			}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, "Email is required"):
			create_member_and_membership(
				member_kind="Individual",
				contact=contact.name,
				existing_address=address.name,
				membership_type=self._membership_type(),
				from_date="2026-07-01",
			)

	def test_guided_individual_reuses_exact_complete_identity(self):
		values = self._guided_person_values()
		first = create_member_and_membership(**values)
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in ("Contact", "Address", "Customer", "Member", "Membership")
		}

		second = create_member_and_membership(**values)

		self.assertEqual(second, first)
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in counts},
			counts,
		)

	def test_guided_individual_rejects_active_non_current_membership(self):
		values = self._guided_person_values()
		first = create_member_and_membership(**values)
		frappe.db.set_value(
			"Membership",
			first["membership"],
			"membership_status",
			"Pending",
			update_modified=False,
		)

		with self.assertRaisesRegex(frappe.ValidationError, "active non-Current Membership"):
			create_member_and_membership(**values)

	def test_guided_membership_preserves_from_date_for_non_administrator(self):
		values = self._guided_person_values(from_date="2026-07-01")
		first = create_member_and_membership(**values)
		frappe.db.set_value(
			"Membership",
			first["membership"],
			{"membership_status": "Expired", "to_date": "2026-07-01"},
			update_modified=False,
		)
		selected_from_date = "2026-08-15"
		frappe.set_user("Guest")
		try:
			membership = get_or_create_membership_for_member(
				first["member"],
				membership_type=self._membership_type(),
				from_date=selected_from_date,
				membership_status="Current",
				keep_to_date_open=True,
				keep_from_date=True,
				ignore_permissions=True,
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(str(membership.from_date), selected_from_date)

	def test_guided_membership_keeps_non_administrator_renewal_guard(self):
		values = self._guided_person_values(from_date="2026-07-01")
		first = create_member_and_membership(**values)
		frappe.db.set_value(
			"Membership",
			first["membership"],
			{"membership_status": "Current", "to_date": "2026-12-31"},
			update_modified=False,
		)
		frappe.set_user("Guest")
		try:
			with self.assertRaisesRegex(frappe.ValidationError, "expires within 30 days"):
				get_or_create_membership_for_member(
					first["member"],
					membership_type=self._membership_type(),
					from_date="2027-01-15",
					membership_status="Current",
					keep_to_date_open=True,
					keep_from_date=True,
					ignore_permissions=True,
				)
		finally:
			frappe.set_user("Administrator")

	def test_guided_creation_requires_from_date(self):
		values = self._guided_person_values(from_date=None)

		with self.assertRaisesRegex(frappe.ValidationError, "From Date is required"):
			create_member_and_membership(**values)

	def test_guided_creation_requires_connector_installed_on_site(self):
		values = self._guided_person_values()
		before = {
			doctype: frappe.db.count(doctype) for doctype in ("Contact", "Address", "Customer", "Member")
		}

		with (
			patch("non_profit.non_profit.member_identity.frappe.get_installed_apps", return_value=[]),
			self.assertRaisesRegex(frappe.ValidationError, "Good Connector identity matching is required"),
		):
			create_member_and_membership(**values)

		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in before},
			before,
		)

	def test_guided_deadlock_is_not_masked_by_savepoint_rollback(self):
		values = self._guided_person_values()
		deadlock = frappe.QueryDeadlockError("simulated deadlock")

		with (
			patch("non_profit.non_profit.member_identity._create_individual", side_effect=deadlock),
			patch.object(frappe.db, "rollback") as rollback,
			self.assertRaises(frappe.QueryDeadlockError),
		):
			create_member_and_membership(**values)

		rollback.assert_not_called()

	def test_guided_individual_rejects_duplicate_exact_addresses(self):
		values = self._guided_person_values()
		first = create_member_and_membership(**values)
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Duplicate Guided Address",
				"address_type": "Billing",
				"address_line1": values["address_line1"],
				"pincode": values["postal_code"],
				"city": values["city"],
				"country": values["country"],
				"links": [{"link_doctype": "Member", "link_name": first["member"]}],
			}
		).insert(ignore_permissions=True)
		before = frappe.db.count("Address")

		with self.assertRaisesRegex(frappe.ValidationError, "More than one exact Address"):
			create_member_and_membership(**values)

		self.assertEqual(frappe.db.count("Address"), before)

	def test_guided_individual_rejects_ambiguous_exact_contacts(self):
		values = self._guided_person_values()
		for _index in range(2):
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": values["first_name"],
					"last_name": values["last_name"],
					"email_ids": [{"email_id": values["email"], "is_primary": 1}],
				}
			).insert(ignore_permissions=True)
		before = {doctype: frappe.db.count(doctype) for doctype in ("Customer", "Member", "Membership")}

		with self.assertRaisesRegex(frappe.ValidationError, "More than one Contact"):
			create_member_and_membership(**values)

		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in before},
			before,
		)

	def test_guided_individual_rejects_generic_endpoint_contact(self):
		values = self._guided_person_values()
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": values["first_name"],
				"last_name": values["last_name"],
				"npo_identity_kind": "Generic Endpoint",
				"email_ids": [{"email_id": values["email"], "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, "not classified as a person"):
			create_member_and_membership(**values)

		self.assertFalse(frappe.db.exists("Member", {"contact": contact.name}))

	def test_guided_individual_rejects_unrelated_same_email_customer_identity(self):
		values = self._guided_person_values()
		unrelated = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Unrelated Same Email Household",
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"email_id": values["email"],
			}
		).insert(ignore_permissions=True)
		unrelated_contact = unrelated.customer_primary_contact

		with self.assertRaisesRegex(frappe.ValidationError, "different or ambiguous Contact"):
			create_member_and_membership(**values)

		self.assertEqual(
			frappe.db.get_value("Customer", unrelated.name, "customer_primary_contact"), unrelated_contact
		)
		self.assertFalse(frappe.db.exists("Member", {"customer": unrelated.name}))

	def test_guided_same_name_people_remain_separate(self):
		membership_type = self._membership_type()
		first = self._guided_person_values(
			membership_type=membership_type,
			first_name="Same",
			last_name="Name",
			email=f"same-name-one-{frappe.generate_hash(length=8)}@example.org",
		)
		second = {
			**first,
			"email": f"same-name-two-{frappe.generate_hash(length=8)}@example.org",
			"address_line1": "Andere Strasse 9",
		}

		first_result = create_member_and_membership(**first)
		second_result = create_member_and_membership(**second)

		self.assertNotEqual(first_result["contact"], second_result["contact"])
		self.assertNotEqual(first_result["customer"], second_result["customer"])
		self.assertNotEqual(first_result["member"], second_result["member"])

	def test_guided_organization_keeps_optional_human_contact_separate(self):
		if not resolve_or_create_contact_from_external_signup:
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		result = create_member_and_membership(
			member_kind="Organization",
			membership_type=self._membership_type(),
			from_date="2026-07-01",
			organization_name=f"Guided Foundation {unique}",
			organization_contact_first_name="Alex",
			organization_contact_last_name="Contact",
			organization_contact_email=f"org-contact-{unique}@example.org",
			organization_contact_phone="+41 41 555 12 34",
			address_line1="Stiftungsweg 3",
			postal_code="6000",
			city="Luzern",
			country="Switzerland",
		)

		member = frappe.get_doc("Member", result["member"])
		customer = frappe.get_doc("Customer", result["customer"])
		contact = frappe.get_doc("Contact", result["contact"])
		address = frappe.get_doc("Address", result["address"])
		self.assertEqual(member.subject_type, "Organization")
		self.assertFalse(member.contact)
		self.assertEqual(customer.customer_type, "Company")
		self.assertEqual(customer.customer_primary_contact, contact.name)
		self.assertTrue(
			any(row.link_doctype == "Member" and row.link_name == member.name for row in contact.links)
		)
		self.assertFalse(any(row.link_doctype == "Contact" for row in address.links))

	def test_guided_organization_uses_explicit_existing_contact(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Existing",
				"last_name": f"Organization Contact {unique}",
				"email_ids": [{"email_id": f"existing-org-contact-{unique}@example.org", "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		result = create_member_and_membership(
			member_kind="Organization",
			contact=contact.name,
			membership_type=self._membership_type(),
			from_date="2026-07-01",
			organization_name=f"Existing Contact Foundation {unique}",
		)

		member = frappe.get_doc("Member", result["member"])
		contact.reload()
		self.assertEqual(result["contact"], contact.name)
		self.assertFalse(member.contact)
		self.assertTrue(
			any(row.link_doctype == "Member" and row.link_name == member.name for row in contact.links)
		)

	def test_guided_organization_allows_omitting_contact_and_address(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		values = {
			"member_kind": "Organization",
			"membership_type": self._membership_type(),
			"from_date": "2026-07-01",
			"organization_name": f"Organization Only {unique}",
		}

		first = create_member_and_membership(**values)
		second = create_member_and_membership(**values)

		member = frappe.get_doc("Member", first["member"])
		self.assertEqual(second, first)
		self.assertEqual(member.subject_type, "Organization")
		self.assertFalse(member.contact)
		self.assertFalse(first["contact"])
		self.assertFalse(first["address"])

	def test_guided_organization_preserves_uncollected_address_values_on_reuse(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		values = {
			"member_kind": "Organization",
			"membership_type": self._membership_type(),
			"from_date": "2026-07-01",
			"organization_name": f"Address Preservation Foundation {unique}",
			"address_line1": "Foundation Lane 7",
			"postal_code": "3000",
			"city": "Bern",
			"country": "Switzerland",
		}
		first = create_member_and_membership(**values)
		frappe.db.set_value(
			"Address",
			first["address"],
			{
				"address_line2": "Suite 4",
				"email_id": f"office-{unique}@example.org",
				"phone": "+41 31 555 10 10",
			},
			update_modified=False,
		)

		second = create_member_and_membership(**values)

		address = frappe.get_doc("Address", second["address"])
		self.assertEqual(second["address"], first["address"])
		self.assertEqual(address.address_line2, "Suite 4")
		self.assertEqual(address.email_id, f"office-{unique}@example.org")
		self.assertEqual(address.phone, "+41 31 555 10 10")

	def test_guided_organization_rejects_same_name_individual_customer(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		organization_name = f"Contradictory Organization {unique}"
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": organization_name,
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, "non-organization type"):
			create_member_and_membership(
				member_kind="Organization",
				membership_type=self._membership_type(),
				from_date="2026-07-01",
				organization_name=organization_name,
			)

	def test_guided_organization_normalizes_name_whitespace_for_reuse(self):
		if "good_connector" not in frappe.get_installed_apps():
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		values = {
			"member_kind": "Organization",
			"membership_type": self._membership_type(),
			"from_date": "2026-07-01",
			"organization_name": f"Normalized  Foundation {unique}",
		}

		first = create_member_and_membership(**values)
		second = create_member_and_membership(
			**{**values, "organization_name": f"Normalized Foundation {unique}"}
		)

		self.assertEqual(second, first)

	def test_guided_late_identity_failure_rolls_back_created_organization(self):
		if not resolve_or_create_contact_from_external_signup:
			self.skipTest("good_connector identity matching is not installed")
		unique = frappe.generate_hash(length=8)
		email = f"ambiguous-org-contact-{unique}@example.org"
		for _index in range(2):
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Ambiguous",
					"last_name": "Contact",
					"email_ids": [{"email_id": email, "is_primary": 1}],
				}
			).insert(ignore_permissions=True)
		organization_name = f"Rollback Foundation {unique}"
		before = {doctype: frappe.db.count(doctype) for doctype in ("Customer", "Member", "Membership")}

		with self.assertRaisesRegex(frappe.ValidationError, "More than one Contact"):
			create_member_and_membership(
				member_kind="Organization",
				membership_type=self._membership_type(),
				from_date="2026-07-01",
				organization_name=organization_name,
				organization_contact_first_name="Ambiguous",
				organization_contact_last_name="Contact",
				organization_contact_email=email,
			)

		self.assertFalse(frappe.db.exists("Customer", {"customer_name": organization_name}))
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in before},
			before,
		)

	def test_guided_permission_failure_happens_before_partial_records(self):
		values = self._guided_person_values()
		before = {
			doctype: frappe.db.count(doctype) for doctype in ("Contact", "Address", "Customer", "Member")
		}

		with patch(
			"non_profit.non_profit.member_identity.frappe.has_permission",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				create_member_and_membership(**values)

		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in before},
			before,
		)

	def test_guided_guest_permission_failure_happens_before_partial_records(self):
		values = self._guided_person_values()
		before = {
			doctype: frappe.db.count(doctype) for doctype in ("Contact", "Address", "Customer", "Member")
		}
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				create_member_and_membership(**values)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in before},
			before,
		)

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
