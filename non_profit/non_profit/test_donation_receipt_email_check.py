"""Tests for the Donation Receipt Email Check report."""

import frappe

from non_profit.non_profit.report.donation_receipt_email_check.donation_receipt_email_check import (
	BLOCKER,
	WARNING,
	execute,
)
from non_profit.non_profit.test_tax_receipts import TaxReceiptFixtures


class TestDonationReceiptEmailCheck(TaxReceiptFixtures):
	def _run(self) -> list[dict]:
		_columns, rows = execute({"company": self.company, "tax_year": self.tax_year})
		return rows

	def _issues_for(self, donor: str) -> set[str]:
		return {row["issue"] for row in self._run() if row["donor"] == donor}

	def test_clean_donor_is_not_reported(self):
		donor, _contact = self._contact_donor("Sauber", email=f"sauber.{self.suffix}@example.com")
		self._donation(donor.name, 100, f"{self.tax_year}-03-01")

		self.assertEqual(self._issues_for(donor.name), set())

	def test_missing_email_is_a_blocker(self):
		donor = self._subjectless_donor()
		self._donation(donor.name, 250, f"{self.tax_year}-04-01")

		rows = [row for row in self._run() if row["donor"] == donor.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["severity"], BLOCKER)
		self.assertIn("No email address", rows[0]["issue"])

	def test_new_donors_cannot_share_an_address_in_the_first_place(self):
		# The identity layer refuses a second donor on an address that is already
		# taken, so the report below is about legacy and imported data, not about
		# what the desk lets an operator type today.
		shared = f"gemeinsam.{self.suffix}@example.com"
		self._contact_donor("Ehepaar A", email=shared)
		with self.assertRaises(frappe.ValidationError):
			self._contact_donor("Ehepaar B", email=shared)

	def test_shared_address_is_a_blocker_and_names_the_other_donor(self):
		shared = f"gemeinsam.{self.suffix}@example.com"
		donor_a, _a = self._contact_donor("Ehepaar A", email=f"a.{self.suffix}@example.com")
		donor_b, contact_b = self._contact_donor("Ehepaar B", email=f"b.{self.suffix}@example.com")
		# Simulate the imported/edited-after-the-fact case the identity layer
		# cannot catch: two contacts ending up on one inbox.
		frappe.db.set_value("Contact", contact_b.name, "email_id", shared, update_modified=False)
		frappe.db.set_value(
			"Contact", _a.name if hasattr(_a, "name") else _a, "email_id", shared, update_modified=False
		)
		self._donation(donor_a.name, 100, f"{self.tax_year}-03-01")
		self._donation(donor_b.name, 100, f"{self.tax_year}-03-02")

		rows = [
			row for row in self._run() if row["donor"] == donor_a.name and "shared" in row["issue"].lower()
		]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["severity"], BLOCKER)
		self.assertIn(donor_b.name, rows[0]["shared_with"])

	def test_role_mailbox_is_a_warning(self):
		donor, _contact = self._contact_donor("Verein", email=f"info@verein-{self.suffix}.example.com")
		self._donation(donor.name, 500, f"{self.tax_year}-06-01")

		rows = [row for row in self._run() if row["donor"] == donor.name]
		self.assertEqual([row["severity"] for row in rows], [WARNING])
		self.assertIn("role mailbox", rows[0]["issue"].lower())

	def test_donations_outside_the_tax_year_are_ignored(self):
		donor = self._subjectless_donor()
		self._donation(donor.name, 250, f"{self.tax_year - 1}-04-01")

		self.assertEqual(self._issues_for(donor.name), set())

	def test_unsubmitted_donations_are_ignored(self):
		donor = self._subjectless_donor()
		self._donation(donor.name, 250, f"{self.tax_year}-04-01", submit=False)

		self.assertEqual(self._issues_for(donor.name), set())

	def test_blockers_sort_before_warnings(self):
		blocked = self._subjectless_donor()
		self._donation(blocked.name, 10, f"{self.tax_year}-03-01")
		warned, _contact = self._contact_donor("Buero", email=f"kontakt@b-{self.suffix}.example.com")
		self._donation(warned.name, 9000, f"{self.tax_year}-03-01")

		severities = [row["severity"] for row in self._run()]
		self.assertEqual(severities[0], BLOCKER, "a blocker outranks a larger warning")
