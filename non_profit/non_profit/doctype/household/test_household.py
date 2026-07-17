# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import call, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from non_profit.non_profit.doctype.donor.donor import Donor
from non_profit.non_profit.doctype.household.household import (
	Household,
	add_member_to_household,
)
from non_profit.non_profit.doctype.member.member import Member
from non_profit.non_profit.doctype.membership.test_membership import (
	make_membership,
	setup_membership,
)


class TestHousehold(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_household_syncs_member_and_donor_links(self) -> None:
		member = self._member("_Test Household Member Sync")
		donor = self._donor("_Test Household Donor Sync")
		household = self._household(
			"_Test Household Party Sync",
			[("Member", member.name), ("Donor", donor.name)],
		)

		self.assertEqual(frappe.db.get_value("Member", member.name, "household"), household.name)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "household"), household.name)

	def test_removed_row_clears_member_and_all_membership_flags(self) -> None:
		setup_membership()
		member = self._member("_Test Household Removed Member")
		household = self._household("_Test Household Removed Row", [("Member", member.name)])
		membership = make_membership(member.name)
		frappe.db.set_value("Membership", membership.name, "membership_status", "Expired")

		household.reload()
		household.set("members", [])
		household.save()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))
		self.assertEqual(
			frappe.db.get_value("Membership", membership.name, "is_household_membership"),
			0,
		)

	def test_retargeted_row_reconciles_both_members_and_memberships(self) -> None:
		setup_membership()
		first = self._member("_Test Household Retarget First")
		second = self._member("_Test Household Retarget Second")
		household = self._household("_Test Household Retarget", [("Member", first.name)])
		first_membership = make_membership(first.name)
		second_membership = make_membership(second.name)

		household.reload()
		household.members[0].link_name = second.name
		household.save()

		self.assertFalse(frappe.db.get_value("Member", first.name, "household"))
		self.assertEqual(frappe.db.get_value("Member", second.name, "household"), household.name)
		self.assertEqual(
			frappe.db.get_value("Membership", first_membership.name, "is_household_membership"),
			0,
		)
		self.assertEqual(
			frappe.db.get_value("Membership", second_membership.name, "is_household_membership"),
			1,
		)

	def test_removed_donor_row_clears_derived_link(self) -> None:
		donor = self._donor("_Test Household Removed Donor")
		household = self._household("_Test Household Donor Removed", [("Donor", donor.name)])

		household.reload()
		household.set("members", [])
		household.save()

		self.assertFalse(frappe.db.get_value("Donor", donor.name, "household"))

	def test_retargeted_donor_row_reconciles_both_donors(self) -> None:
		first = self._donor("_Test Household Retarget Donor First")
		second = self._donor("_Test Household Retarget Donor Second")
		household = self._household("_Test Household Retarget Donor", [("Donor", first.name)])

		household.reload()
		household.members[0].link_name = second.name
		household.save()

		self.assertFalse(frappe.db.get_value("Donor", first.name, "household"))
		self.assertEqual(frappe.db.get_value("Donor", second.name, "household"), household.name)

	def test_to_date_clears_member_link_and_membership_flag(self) -> None:
		setup_membership()
		member = self._member("_Test Household Member Leaving")
		household = self._household("_Test Household Leaving", [("Member", member.name)])
		membership = make_membership(member.name)

		household.reload()
		household.members[0].to_date = nowdate()
		household.save()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))
		self.assertEqual(
			frappe.db.get_value("Membership", membership.name, "is_household_membership"),
			0,
		)

	def test_delete_reconciles_party_link(self) -> None:
		member = self._member("_Test Household Deleted Member")
		household = self._household("_Test Household Deleted", [("Member", member.name)])

		household.delete()

		self.assertFalse(frappe.db.get_value("Member", member.name, "household"))

	def test_rejects_second_current_household(self) -> None:
		member = self._member("_Test Household Member Conflict")
		first = self._household("_Test Household First", [("Member", member.name)])
		conflicting = self._new_household("_Test Household Second", [("Member", member.name)])

		with self.assertRaises(frappe.ValidationError):
			conflicting.insert(ignore_permissions=True)

		first.reload()
		first.members[0].to_date = nowdate()
		first.save()
		second = self._household("_Test Household Second", [("Member", member.name)])
		self.assertEqual(frappe.db.get_value("Member", member.name, "household"), second.name)

	def test_rejects_duplicate_current_party_rows(self) -> None:
		member = self._member("_Test Household Duplicate Member")
		household = self._new_household(
			"_Test Household Duplicate Rows",
			[("Member", member.name), ("Member", member.name)],
		)

		with self.assertRaises(frappe.ValidationError):
			household.insert(ignore_permissions=True)

	def test_rejects_multiple_current_primary_rows(self) -> None:
		first = self._member("_Test Household Primary First")
		second = self._member("_Test Household Primary Second")
		household = self._new_household(
			"_Test Household Multiple Primary",
			[("Member", first.name), ("Member", second.name)],
		)
		for row in household.members:
			row.is_primary = 1

		with self.assertRaises(frappe.ValidationError):
			household.insert(ignore_permissions=True)

	def test_requires_from_date_and_valid_date_order(self) -> None:
		member = self._member("_Test Household Dates Member")
		missing_from_date = self._new_household(
			"_Test Household Missing From Date",
			[("Member", member.name)],
		)
		missing_from_date.members[0].from_date = None
		with self.assertRaises(frappe.ValidationError):
			missing_from_date.insert(ignore_permissions=True)

		invalid_order = self._new_household(
			"_Test Household Invalid Dates",
			[("Member", member.name)],
		)
		invalid_order.members[0].to_date = add_days(nowdate(), -1)
		with self.assertRaises(frappe.ValidationError):
			invalid_order.insert(ignore_permissions=True)

	def test_party_household_fields_are_derived_and_read_only(self) -> None:
		member = self._member("_Test Household Derived Member")
		donor = self._donor("_Test Household Derived Donor")
		household = self._household(
			"_Test Household Derived Fields",
			[("Member", member.name), ("Donor", donor.name)],
		)

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

	def test_party_validation_reads_household_without_child_row_locks(self) -> None:
		member = self._member("_Test Household Non Locking Member")
		donor = self._donor("_Test Household Non Locking Donor")

		with patch(
			"non_profit.non_profit.doctype.household.household._get_current_households",
			return_value=[],
		) as get_current_households:
			member.validate()
			donor.validate()

		self.assertEqual(
			get_current_households.call_args_list,
			[call("Member", member.name), call("Donor", donor.name)],
		)

	def test_household_permissions_match_donor_manager_access(self) -> None:
		household_roles = {permission.role for permission in frappe.get_meta("Household").permissions}
		donor_roles = {permission.role for permission in frappe.get_meta("Donor").permissions}

		self.assertTrue(household_roles.issubset(donor_roles))
		self.assertIn("Non Profit Manager", household_roles)
		self.assertNotIn("Non Profit Member", household_roles)

	def test_household_save_requires_target_donor_write_permission(self) -> None:
		donor = self._donor("_Test Household Target Permission Donor")
		household = self._household("_Test Household Target Permission", [("Donor", donor.name)])
		household.reload()
		household.flags.ignore_permissions = False

		with patch.object(Donor, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				household.save()

	def test_service_adds_dated_member_and_syncs_link(self) -> None:
		member = self._member("_Test Household Service Member")
		household = self._household("_Test Household Service", [])

		result = add_member_to_household(
			household.name,
			member.name,
			nowdate(),
			is_primary=True,
			ignore_permissions=True,
		)

		self.assertEqual(result.members[-1].link_name, member.name)
		self.assertEqual(result.members[-1].from_date, nowdate())
		self.assertEqual(result.members[-1].is_primary, 1)
		self.assertEqual(frappe.db.get_value("Member", member.name, "household"), household.name)

	def test_service_requires_household_write_permission(self) -> None:
		member = self._member("_Test Household Service Permission Member")
		household = self._household("_Test Household Service Permission", [])

		with patch.object(Household, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				add_member_to_household(household.name, member.name, nowdate())

	def test_service_requires_member_write_permission(self) -> None:
		member = self._member("_Test Household Service Member Permission")
		household = self._household("_Test Household Service Member Permission", [])

		with patch.object(Member, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				add_member_to_household(household.name, member.name, nowdate())

	def _member(self, member_name: str):
		return frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": member_name,
				"email_id": f"{frappe.scrub(member_name)}@example.com",
			}
		).insert(ignore_permissions=True)

	def _donor(self, donor_name: str):
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
			}
		).insert(ignore_permissions=True)

	def _new_household(self, household_name: str, parties: list[tuple[str, str]]):
		return frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": household_name,
				"members": [
					{
						"link_doctype": doctype,
						"link_name": name,
						"from_date": nowdate(),
					}
					for doctype, name in parties
				],
			}
		)

	def _household(self, household_name: str, parties: list[tuple[str, str]]):
		return self._new_household(household_name, parties).insert(ignore_permissions=True)
