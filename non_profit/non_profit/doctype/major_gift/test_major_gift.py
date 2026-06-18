# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate


class TestMajorGift(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_expected_amount_defaults_and_weighted_value(self) -> None:
		gift = self._major_gift(stage="Solicitation", ask_amount=10000)
		self.assertEqual(gift.expected_amount, 10000)
		self.assertEqual(gift.probability, 60)
		self.assertEqual(gift.weighted_amount, 6000)

	def test_won_stage_stamps_outcome_and_forces_probability(self) -> None:
		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		self.assertEqual(gift.probability, 40)
		gift.stage = "Won"
		gift.save()
		self.assertEqual(gift.outcome, "Won")
		self.assertEqual(gift.probability, 100)
		self.assertTrue(gift.closed_on)
		self.assertEqual(gift.weighted_amount, 5000)

	def test_closed_amount_sums_linked_paid_donations(self) -> None:
		gift = self._major_gift(stage="Solicitation", ask_amount=8000)
		self._donation(donor=gift.donor, amount=3000, major_gift=gift.name)
		self._donation(donor=gift.donor, amount=2000, major_gift=gift.name)
		gift.reload()
		self.assertEqual(gift.closed_amount, 5000)

	def test_donor_giving_rollups(self) -> None:
		donor = self._donor()
		self._donation(donor=donor.name, amount=120)
		self._donation(donor=donor.name, amount=480)
		donor.reload()
		self.assertEqual(donor.total_lifetime_amount, 600)
		self.assertEqual(donor.gift_count, 2)
		self.assertEqual(donor.largest_gift_amount, 480)
		self.assertEqual(donor.last_gift_amount, 480)

	def test_major_donor_flag_from_threshold(self) -> None:
		frappe.db.set_single_value("Non Profit Settings", "major_donor_threshold", 1000)
		donor = self._donor()
		self._donation(donor=donor.name, amount=1500)
		donor.reload()
		self.assertTrue(donor.is_major_donor)

	# --- helpers -----------------------------------------------------------

	def _major_gift(self, stage: str, ask_amount: float):
		donor = self._donor()
		return frappe.get_doc(
			{
				"doctype": "Major Gift",
				"donor": donor.name,
				"stage": stage,
				"ask_amount": ask_amount,
			}
		).insert(ignore_permissions=True)

	def _donation(self, donor: str, amount: float, major_gift: str | None = None):
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": self._company(),
				"donor": donor,
				"campaign": None,
				"major_gift": major_gift,
				"date": nowdate(),
				"amount": amount,
				"paid": 1,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		return donation

	def _donor(self):
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Major Gift Donor {frappe.generate_hash(length=8)}",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)

	def _donor_type(self) -> str:
		name = f"Major Gift Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name

	def _company(self) -> str | None:
		return frappe.db.get_single_value("Non Profit Settings", "company") or frappe.db.get_value(
			"Company",
			{},
			"name",
			order_by="name asc",
		)
