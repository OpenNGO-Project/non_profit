"""Each migrated doctype must own its naming-series counter."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.setup import NAMING_SERIES_KEYS, seed_naming_series_counters


class TestNamingSeries(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_each_migrated_doctype_owns_its_naming_series_counter(self):
		"""``format:NPO-ORG-{#####}`` resolved to the empty series key.

		Frappe resolves each braced parameter on its own, so the counter prefix
		was built from nothing and every such doctype in the bench drew from one
		shared ``tabSeries`` row — visible as adjacent numbers across unrelated
		doctypes and as lock contention on that single row.
		"""
		for doctype, prefix in NAMING_SERIES_KEYS.items():
			with self.subTest(doctype=doctype):
				autoname = frappe.get_meta(doctype).autoname
				self.assertEqual(autoname, f"{prefix}.#####.")
				self.assertFalse(autoname.startswith("format:"))

	def test_a_new_document_draws_from_its_own_counter(self):
		organization = self._make_organization()
		self.assertRegex(organization.name, r"^NPO-ORG-\d{5,}$")
		row = frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = 'NPO-ORG-'")
		self.assertTrue(row, "inserting must create the NPO-ORG- counter, not feed ''")
		self.assertEqual(row[0][0], int(organization.name.rsplit("-", 1)[1]))

	def test_seeding_lifts_a_counter_to_the_highest_name_in_use(self):
		organization = self._make_organization()
		used = int(organization.name.rsplit("-", 1)[1])

		frappe.db.sql("DELETE FROM `tabSeries` WHERE name = 'NPO-ORG-'")
		seed_naming_series_counters()

		current = frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = 'NPO-ORG-'")
		self.assertTrue(current, "seeding must create the counter")
		self.assertGreaterEqual(
			current[0][0], used, "a reseeded counter must never re-issue an existing name"
		)

	def test_seeding_never_lowers_a_counter_that_is_already_ahead(self):
		self._make_organization()
		frappe.db.sql("UPDATE `tabSeries` SET current = 999999 WHERE name = 'NPO-ORG-'")

		seed_naming_series_counters()

		current = frappe.db.sql("SELECT current FROM `tabSeries` WHERE name = 'NPO-ORG-'")
		self.assertEqual(current[0][0], 999999)

	def _make_organization(self):
		return frappe.get_doc(
			doctype="NPO Organization",
			organization_name="Naming series probe",
		).insert(ignore_permissions=True)
