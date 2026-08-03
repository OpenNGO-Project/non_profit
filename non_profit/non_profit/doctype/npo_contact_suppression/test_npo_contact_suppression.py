from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.non_profit.contact_suppression import active_suppressed_contacts


class TestNPOContactSuppression(IntegrationTestCase):
	def tearDown(self) -> None:
		for name in frappe.get_all(
			"NPO Contact Suppression",
			filters={"reason": ("like", "_NPCS%")},
			pluck="name",
		):
			frappe.delete_doc("NPO Contact Suppression", name, force=True, ignore_permissions=True)
		super().tearDown()

	def _contact(self, first_name: str, identity_kind: str = "Person"):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": frappe.generate_hash(length=8),
				"npo_identity_kind": identity_kind,
			}
		).insert(ignore_permissions=True)

	def _suppression(self, contact: str, **overrides):
		return frappe.get_doc(
			{
				"doctype": "NPO Contact Suppression",
				"contact": contact,
				"scope": "Do Not Contact",
				"reason": "_NPCS test row",
				**overrides,
			}
		).insert(ignore_permissions=True)

	def test_generic_endpoint_contacts_are_rejected(self) -> None:
		endpoint = self._contact("Endpoint", identity_kind="Generic Endpoint")
		with self.assertRaisesRegex(frappe.ValidationError, "Generic Endpoint"):
			self._suppression(endpoint.name)

	def test_active_suppressed_contacts_returns_only_active_rows_for_requested_names(self) -> None:
		suppressed = self._contact("Suppressed")
		deceased = self._contact("Deceased")
		retired = self._contact("Retired")
		untouched = self._contact("Untouched")
		self._suppression(suppressed.name)
		self._suppression(deceased.name, scope="Deceased")
		self._suppression(retired.name, active=0)

		result = active_suppressed_contacts(
			[suppressed.name, deceased.name, retired.name, untouched.name, "", "  "]
		)

		self.assertEqual(result, {suppressed.name, deceased.name})
		# A suppression outside the requested names never leaks into the result.
		self.assertEqual(active_suppressed_contacts([untouched.name]), set())
		self.assertEqual(active_suppressed_contacts([]), set())
