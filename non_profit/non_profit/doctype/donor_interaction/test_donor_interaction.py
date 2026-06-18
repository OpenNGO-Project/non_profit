# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate


class TestDonorInteraction(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_latest_interaction_syncs_to_donor(self) -> None:
		donor = self._donor()
		self._interaction(donor.name, "2026-01-10 09:00:00")
		latest = self._interaction(donor.name, "2026-03-15 14:00:00")
		donor.reload()
		self.assertEqual(getdate(donor.last_interaction_date), getdate("2026-03-15"))

		# Deleting the latest touchpoint falls back to the earlier one.
		latest.delete()
		donor.reload()
		self.assertEqual(getdate(donor.last_interaction_date), getdate("2026-01-10"))

	def test_interaction_syncs_to_major_gift(self) -> None:
		donor = self._donor()
		gift = frappe.get_doc({"doctype": "Major Gift", "donor": donor.name, "stage": "Cultivation"}).insert(
			ignore_permissions=True
		)
		self._interaction(donor.name, "2026-02-20 10:00:00", major_gift=gift.name)
		gift.reload()
		self.assertEqual(getdate(gift.last_interaction_date), getdate("2026-02-20"))

	def test_staff_defaults_to_session_user(self) -> None:
		donor = self._donor()
		interaction = self._interaction(donor.name, None, staff=None)
		self.assertEqual(interaction.staff, "Administrator")
		self.assertTrue(interaction.interaction_date)

	# --- helpers -----------------------------------------------------------

	def _interaction(
		self,
		donor: str,
		when: str | None,
		staff: str | None = "Administrator",
		interaction_type: str = "Call",
		major_gift: str | None = None,
	):
		return frappe.get_doc(
			{
				"doctype": "Donor Interaction",
				"donor": donor,
				"major_gift": major_gift,
				"interaction_type": interaction_type,
				"interaction_date": when,
				"staff": staff,
				"subject": "Test touchpoint",
			}
		).insert(ignore_permissions=True)

	def _donor(self):
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Interaction Donor {frappe.generate_hash(length=8)}",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)

	def _donor_type(self) -> str:
		name = f"Interaction Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name
