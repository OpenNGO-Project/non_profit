from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.patches.migrate_household_members_to_people import (
	OLD_DOCTYPE,
	_legacy_source,
	_validate_and_coalesce_rows,
)
from non_profit.setup import make_custom_fields


class TestPartyModelSchema(IntegrationTestCase):
	def test_standard_party_fields_are_installed_idempotently(self) -> None:
		make_custom_fields()
		make_custom_fields()

		expected_fields = {
			"Contact": {"npo_identity_kind"},
			"Customer": {"npo_subject_type", "npo_contact", "npo_organization", "npo_household"},
			"Supplier": {"npo_subject_type", "npo_contact", "npo_organization"},
		}
		for doctype, fieldnames in expected_fields.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				with self.subTest(doctype=doctype, fieldname=fieldname):
					field = meta.get_field(fieldname)
					self.assertIsNotNone(field)
					self.assertTrue(frappe.db.has_column(doctype, fieldname))
					self.assertTrue(field.hidden)
					self.assertTrue(field.read_only)
					self.assertEqual(
						frappe.db.get_value(
							"Custom Field",
							{"dt": doctype, "fieldname": fieldname},
							"module",
						),
						"Non Profit",
					)

	def test_role_fields_are_nullable_and_preparatory(self) -> None:
		expected_fields = {
			"Member": {"subject_type", "contact"},
			"Donor": {"subject_type", "contact", "subject_household"},
			"Volunteer": {"contact"},
		}
		for doctype, fieldnames in expected_fields.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				with self.subTest(doctype=doctype, fieldname=fieldname):
					field = meta.get_field(fieldname)
					self.assertIsNotNone(field)
					self.assertFalse(field.reqd)
					self.assertTrue(field.hidden)
					self.assertTrue(field.read_only)

	def test_household_uses_contact_based_people(self) -> None:
		household_meta = frappe.get_meta("Household")
		self.assertEqual(household_meta.get_field("members").options, "Household Person")

		person_meta = frappe.get_meta("Household Person")
		self.assertTrue(person_meta.istable)
		self.assertTrue(person_meta.get_field("contact").reqd)
		self.assertTrue(person_meta.get_field("from_date").reqd)

	def test_household_migration_patches_are_ordered_around_model_sync(self) -> None:
		with open(frappe.get_app_path("non_profit", "patches.txt")) as patches_file:
			patches = patches_file.read()

		pre_section, post_section = patches.split("[post_model_sync]")
		self.assertIn("non_profit.patches.migrate_household_members_to_people", pre_section)
		self.assertIn("non_profit.patches.finalize_household_person_migration", post_section)

	def test_household_migration_recovers_an_orphan_old_table(self) -> None:
		def doctype_exists(doctype: str, name: str) -> bool:
			return doctype == "DocType" and name == "Household Person"

		with (
			patch(
				"non_profit.patches.migrate_household_members_to_people.frappe.db.table_exists",
				return_value=True,
			),
			patch(
				"non_profit.patches.migrate_household_members_to_people.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"non_profit.patches.migrate_household_members_to_people.frappe.db.exists",
				side_effect=doctype_exists,
			),
			patch(
				"non_profit.patches.migrate_household_members_to_people._table_has_rows",
				return_value=True,
			),
		):
			self.assertEqual(_legacy_source(), (OLD_DOCTYPE, "copy"))

	def test_household_migration_coalesces_same_person_role_rows(self) -> None:
		rows = [
			frappe._dict(
				name="legacy-member-row",
				parent="Legacy Household",
				link_doctype="Member",
				link_name="MEM-1",
				contact="CONTACT-1",
				from_date="2026-01-01",
				to_date=None,
				is_primary=1,
			),
			frappe._dict(
				name="legacy-donor-row",
				parent="Legacy Household",
				link_doctype="Donor",
				link_name="DON-1",
				contact="CONTACT-1",
				from_date="2026-01-01",
				to_date=None,
				is_primary=0,
			),
		]

		kept_rows, duplicate_names = _validate_and_coalesce_rows(rows)

		self.assertEqual([row.name for row in kept_rows], ["legacy-member-row"])
		self.assertEqual(duplicate_names, ["legacy-donor-row"])
		self.assertEqual(kept_rows[0].is_primary, 1)

	def test_household_migration_rejects_conflicting_current_history(self) -> None:
		rows = [
			frappe._dict(
				name="legacy-row-1",
				parent="First Household",
				link_doctype="Member",
				link_name="MEM-1",
				contact="CONTACT-1",
				from_date="2026-01-01",
				to_date=None,
				is_primary=0,
			),
			frappe._dict(
				name="legacy-row-2",
				parent="Second Household",
				link_doctype="Donor",
				link_name="DON-1",
				contact="CONTACT-1",
				from_date="2026-01-01",
				to_date=None,
				is_primary=0,
			),
		]

		with self.assertRaisesRegex(frappe.ValidationError, "conflicting current Household rows"):
			_validate_and_coalesce_rows(rows)

	def test_household_migration_rejects_invalid_dates_and_primary_rows(self) -> None:
		rows = [
			frappe._dict(
				name="legacy-primary-1",
				parent="Legacy Household",
				link_doctype="Member",
				link_name="MEM-1",
				contact="CONTACT-1",
				from_date="2026-01-01",
				to_date=None,
				is_primary=1,
			),
			frappe._dict(
				name="legacy-primary-2",
				parent="Legacy Household",
				link_doctype="Donor",
				link_name="DON-2",
				contact="CONTACT-2",
				from_date="2026-01-01",
				to_date=None,
				is_primary=1,
			),
			frappe._dict(
				name="legacy-invalid-date",
				parent="Legacy Household",
				link_doctype="Donor",
				link_name="DON-3",
				contact="CONTACT-3",
				from_date="2026-02-01",
				to_date="2026-01-01",
				is_primary=0,
			),
		]

		with self.assertRaisesRegex(frappe.ValidationError, "multiple current primary rows"):
			_validate_and_coalesce_rows(rows)

	def test_npo_organization_uses_a_human_title(self) -> None:
		organization = frappe.get_doc(
			{
				"doctype": "NPO Organization",
				"organization_name": "_Test Party Model Organization",
				"country": "Switzerland",
			}
		).insert(ignore_permissions=True)

		self.assertTrue(organization.name.startswith("NPO-ORG-"))
		self.assertEqual(frappe.get_meta("NPO Organization").title_field, "organization_name")
