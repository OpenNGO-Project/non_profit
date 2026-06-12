import frappe
from frappe.tests.utils import FrappeTestCase


class TestDonationReceipt(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_receipt_can_be_saved_before_donations_are_added(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
			}
		).insert(ignore_permissions=True)

		self.assertTrue(receipt.name)
		self.assertFalse(receipt.donations)
		self.assertEqual(receipt.total_amount, 0)

	def test_selected_year_helper_returns_unreceipted_paid_donations(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			get_donations_for_selected_year,
		)

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=42)

		result = get_donations_for_selected_year(fiscal_year=fiscal_year, donor=donor.name)

		donation_names = [row["donation"] for row in result["donations"]]
		self.assertIn(donation.name, donation_names)
		row = next(row for row in result["donations"] if row["donation"] == donation.name)
		self.assertEqual(row["amount"], 42)

	def test_receipt_total_is_computed_from_donation_rows(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=55)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(receipt.total_amount, 55)
		self.assertEqual(receipt.donations[0].amount, 55)

	def test_receipt_submit_requires_donation_rows(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

	def test_receipt_submit_rejects_cross_donor_and_unpaid_donations(self) -> None:
		donor = self._donor()
		other_donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		other_donation = self._donation(other_donor, fiscal_year, amount=60)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": other_donation.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

		unpaid = self._donation(donor, fiscal_year, amount=61, paid=0)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": unpaid.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

	def test_receipt_submit_rejects_already_receipted_donation(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=62)
		first_receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)
		first_receipt.submit()

		second_receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			second_receipt.submit()

	def test_receipt_submit_accepts_string_period_dates_from_form_payload(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=64)
		fy = frappe.get_doc("Fiscal Year", fiscal_year)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"period_from": str(fy.year_start_date),
				"period_to": str(fy.year_end_date),
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		receipt.period_from = str(receipt.period_from)
		receipt.period_to = str(receipt.period_to)
		receipt.submit()

		self.assertEqual(receipt.docstatus, 1)

	def test_yearly_receipt_generation_excludes_existing_draft_rows(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import generate_yearly_receipts

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		self._donation(donor, fiscal_year, amount=63)

		first = generate_yearly_receipts(fiscal_year=fiscal_year, country=self._country())
		second = generate_yearly_receipts(fiscal_year=fiscal_year, country=self._country())

		self.assertGreaterEqual(first["created"], 1)
		self.assertEqual(second["created"], 0)

	def _donor(self):
		donor_type = self._donor_type()
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Receipt Donor {frappe.generate_hash(length=8)}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)

	def _donor_type(self) -> str:
		name = f"Receipt Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name

	def _donation(self, donor, fiscal_year: str, amount: float, paid: int = 1, submit: bool = True):
		fy = frappe.get_doc("Fiscal Year", fiscal_year)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": self._company(),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"date": fy.year_start_date,
				"amount": amount,
				"paid": paid,
			}
		).insert(ignore_permissions=True)
		if submit:
			donation.submit()
		return donation

	def _fiscal_year(self) -> str | None:
		return frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			"name",
			order_by="year_start_date desc",
		)

	def _company(self) -> str | None:
		return frappe.db.get_single_value("Non Profit Settings", "company") or frappe.db.get_value(
			"Company", {}, "name", order_by="name asc"
		)

	def _country(self) -> str | None:
		return (
			"Switzerland"
			if frappe.db.exists("Country", "Switzerland")
			else frappe.db.get_value("Country", {}, "name", order_by="name asc")
		)
