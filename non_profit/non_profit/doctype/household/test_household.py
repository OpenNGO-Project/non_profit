# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import call, patch

import frappe
from frappe.contacts.doctype.contact.contact import Contact
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from non_profit.non_profit.doctype.household.household import (
	Household,
	add_person_to_household,
)
from non_profit.non_profit.doctype.member.member import get_or_create_member_for_contact
from non_profit.non_profit.doctype.membership.test_membership import make_membership, setup_membership

IGNORE_TEST_RECORD_DEPENDENCIES = ["Contact"]


class TestHousehold(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_household_syncs_every_role_for_one_contact(self) -> None:
		contact = self._contact("_Test Household Shared Person")
		member = self._member("_Test Household Shared Member", contact.name)
		donor = self._donor("_Test Household Shared Donor", contact.name)
		household = self._household("_Test Household Shared Roles", [contact.name])

		self.assertEqual(frappe.db.get_value("Member", member.name, "household"), household.name)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "household"), household.name)

	def test_linking_existing_role_refreshes_household_projection(self) -> None:
		setup_membership()
		email = f"household-role-{frappe.generate_hash(length=8)}@example.org"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "_Test Household Existing Role",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		household = self._household("_Test Household Existing Role", [contact.name])
		member = frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": "_Test Household Existing Role",
				"email_id": email,
			}
		).insert(ignore_permissions=True)
		membership = make_membership(member.name)

		linked_member = get_or_create_member_for_contact(contact.name, ignore_permissions=True)

		self.assertEqual(linked_member.name, member.name)
		self.assertEqual(linked_member.household, household.name)
		self.assertEqual(frappe.db.get_value("Membership", membership.name, "is_household_membership"), 1)

	def test_removed_row_clears_roles_and_membership_flags(self) -> None:
		setup_membership()
		contact = self._contact("_Test Household Removed Person")
		member = self._member("_Test Household Removed Member", contact.name)
		donor = self._donor("_Test Household Removed Donor", contact.name)
		household = self._household("_Test Household Removed Row", [contact.name])
		membership = make_membership(member.name)

		household.reload()
		household.set("members", [])
		household.save()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))
		self.assertFalse(frappe.db.get_value("Donor", donor.name, "household"))
		self.assertEqual(frappe.db.get_value("Membership", membership.name, "is_household_membership"), 0)

	def test_retargeted_row_reconciles_old_and_new_contacts(self) -> None:
		first_contact = self._contact("_Test Household Retarget First")
		second_contact = self._contact("_Test Household Retarget Second")
		first_member = self._member("_Test Household Retarget First Member", first_contact.name)
		second_member = self._member("_Test Household Retarget Second Member", second_contact.name)
		household = self._household("_Test Household Retarget", [first_contact.name])

		household.reload()
		household.members[0].contact = second_contact.name
		household.save()

		self.assertFalse(frappe.db.get_value("Member", first_member.name, "household"))
		self.assertEqual(frappe.db.get_value("Member", second_member.name, "household"), household.name)

	def test_to_date_preserves_history_and_clears_current_role_link(self) -> None:
		contact = self._contact("_Test Household Leaving Person")
		member = self._member("_Test Household Leaving Member", contact.name)
		household = self._household("_Test Household Leaving", [contact.name])

		household.reload()
		household.members[0].to_date = nowdate()
		household.save()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))
		self.assertEqual(frappe.db.count("Household Person", {"parent": household.name}), 1)

	def test_delete_reconciles_derived_role_link(self) -> None:
		contact = self._contact("_Test Household Deleted Person")
		member = self._member("_Test Household Deleted Member", contact.name)
		household = self._household("_Test Household Deleted", [contact.name])

		household.delete()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))

	def test_delete_requires_contact_write_permission(self) -> None:
		contact = self._contact("_Test Household Delete Permission Person")
		household = self._household("_Test Household Delete Permission", [contact.name])
		household.reload()
		household.flags.ignore_permissions = False

		with patch.object(Contact, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				household.delete()

	def test_rejects_second_current_household_for_contact(self) -> None:
		contact = self._contact("_Test Household Conflict Person")
		first = self._household("_Test Household First", [contact.name])

		with self.assertRaises(frappe.ValidationError):
			self._new_household("_Test Household Second", [contact.name]).insert(ignore_permissions=True)

		first.reload()
		first.members[0].to_date = nowdate()
		first.save()
		second = self._household("_Test Household Second", [contact.name])
		self.assertEqual(second.members[0].contact, contact.name)

	def test_rejects_duplicate_current_contact_rows(self) -> None:
		contact = self._contact("_Test Household Duplicate Person")
		household = self._new_household(
			"_Test Household Duplicate Rows",
			[contact.name, contact.name],
		)

		with self.assertRaises(frappe.ValidationError):
			household.insert(ignore_permissions=True)

	def test_rejects_generic_endpoint_contact(self) -> None:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "_Test Household Shared Mailbox",
				"npo_identity_kind": "Generic Endpoint",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._new_household("_Test Household Shared Mailbox", [contact.name]).insert(
				ignore_permissions=True
			)

	def test_household_person_cannot_be_reclassified_as_generic_endpoint(self) -> None:
		contact = self._contact("_Test Household Reclassification Person")
		self._household("_Test Household Reclassification", [contact.name])
		contact.npo_identity_kind = "Generic Endpoint"

		with self.assertRaisesRegex(frappe.ValidationError, "used in a Household"):
			contact.save(ignore_permissions=True)

	def test_rejects_multiple_current_primary_rows(self) -> None:
		first = self._contact("_Test Household Primary First")
		second = self._contact("_Test Household Primary Second")
		household = self._new_household("_Test Household Multiple Primary", [first.name, second.name])
		for row in household.members:
			row.is_primary = 1

		with self.assertRaises(frappe.ValidationError):
			household.insert(ignore_permissions=True)

	def test_requires_from_date_and_valid_date_order(self) -> None:
		contact = self._contact("_Test Household Dates Person")
		missing_from_date = self._new_household("_Test Household Missing From Date", [contact.name])
		missing_from_date.members[0].from_date = None
		with self.assertRaises(frappe.ValidationError):
			missing_from_date.insert(ignore_permissions=True)

		invalid_order = self._new_household("_Test Household Invalid Dates", [contact.name])
		invalid_order.members[0].to_date = add_days(nowdate(), -1)
		with self.assertRaises(frappe.ValidationError):
			invalid_order.insert(ignore_permissions=True)

	def test_role_household_fields_are_derived_from_contact(self) -> None:
		contact = self._contact("_Test Household Derived Person")
		member = self._member("_Test Household Derived Member", contact.name)
		donor = self._donor("_Test Household Derived Donor", contact.name)
		household = self._household("_Test Household Derived Fields", [contact.name])

		member.reload()
		member.household = None
		member.save(ignore_permissions=True)
		donor.reload()
		donor.household = None
		donor.save(ignore_permissions=True)

		self.assertEqual(member.household, household.name)
		self.assertEqual(donor.household, household.name)
		self.assertTrue(frappe.get_meta("Member").get_field("household").read_only)
		self.assertTrue(frappe.get_meta("Donor").get_field("household").read_only)

	def test_role_validation_uses_contact_household_lookup(self) -> None:
		contact = self._contact("_Test Household Non Locking Person")
		member = self._member("_Test Household Non Locking Member", contact.name)
		donor = self._donor("_Test Household Non Locking Donor", contact.name)

		with patch(
			"non_profit.non_profit.doctype.household.household._get_current_households",
			return_value=[],
		) as get_current_households:
			member.validate()
			donor.validate()

		self.assertEqual(
			get_current_households.call_args_list,
			[call(contact.name, exclude=None), call(contact.name, exclude=None)],
		)

	def test_household_permissions_match_donor_manager_access(self) -> None:
		household_roles = {permission.role for permission in frappe.get_meta("Household").permissions}
		donor_roles = {permission.role for permission in frappe.get_meta("Donor").permissions}

		self.assertTrue(household_roles.issubset(donor_roles))
		self.assertIn("Non Profit Manager", household_roles)
		self.assertNotIn("Non Profit Member", household_roles)

	def test_household_save_requires_contact_write_permission(self) -> None:
		contact = self._contact("_Test Household Target Permission Person")
		household = self._household("_Test Household Target Permission", [contact.name])
		household.reload()
		household.flags.ignore_permissions = False

		with patch.object(Contact, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				household.save()

	def test_service_adds_dated_contact_and_syncs_roles(self) -> None:
		contact = self._contact("_Test Household Service Person")
		member = self._member("_Test Household Service Member", contact.name)
		household = self._household("_Test Household Service", [])

		result = add_person_to_household(
			household.name,
			contact.name,
			nowdate(),
			is_primary=True,
			relationship="Primary",
			ignore_permissions=True,
		)

		self.assertEqual(result.members[-1].contact, contact.name)
		self.assertEqual(result.members[-1].relationship, "Primary")
		self.assertEqual(result.members[-1].from_date, nowdate())
		self.assertEqual(result.members[-1].is_primary, 1)
		self.assertEqual(frappe.db.get_value("Member", member.name, "household"), household.name)

	def test_service_requires_household_write_permission(self) -> None:
		contact = self._contact("_Test Household Service Permission Person")
		household = self._household("_Test Household Service Permission", [])

		with patch.object(Household, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				add_person_to_household(household.name, contact.name, nowdate())

	def test_service_requires_contact_write_permission(self) -> None:
		contact = self._contact("_Test Household Contact Permission Person")
		household = self._household("_Test Household Contact Permission", [])

		with patch.object(Contact, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				add_person_to_household(household.name, contact.name, nowdate())

	def _contact(self, label: str):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": label,
				"npo_identity_kind": "Person",
			}
		).insert(ignore_permissions=True)

	def _member(self, member_name: str, contact: str):
		return frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": member_name,
				"subject_type": "Individual",
				"contact": contact,
			}
		).insert(ignore_permissions=True)

	def _donor(self, donor_name: str, contact: str):
		donor_type = frappe.db.get_value("Donor Type", {}, "name")
		if not donor_type:
			donor_type = (
				frappe.get_doc({"doctype": "Donor Type", "donor_type": "_Test Household Individual"})
				.insert(ignore_permissions=True)
				.name
			)
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": donor_name,
				"donor_type": donor_type,
				"subject_type": "Individual",
				"contact": contact,
			}
		).insert(ignore_permissions=True)

	def _new_household(self, household_name: str, contacts: list[str]):
		return frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": household_name,
				"members": [
					{
						"contact": contact,
						"from_date": nowdate(),
					}
					for contact in contacts
				],
			}
		)

	def _household(self, household_name: str, contacts: list[str]):
		return self._new_household(household_name, contacts).insert(ignore_permissions=True)
