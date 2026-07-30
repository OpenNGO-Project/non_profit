from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
	RecurringDonation,
	process_recurring_donations,
)


class TestRecurringDonation(UnitTestCase):
	def test_current_installment_is_reused(self) -> None:
		recurring = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-TEST",
				"next_date": "2026-07-01",
			}
		)
		existing = Mock(name="existing donation")
		with (
			patch.object(frappe.db, "get_value", return_value="DON-TEST") as get_value,
			patch.object(frappe, "get_doc", return_value=existing) as get_doc,
			patch.object(recurring, "create_donation") as create_donation,
		):
			result = recurring._get_or_create_current_donation()

		self.assertIs(result, existing)
		self.assertTrue(get_value.call_args.kwargs["for_update"])
		get_doc.assert_called_once_with("Donation", "DON-TEST", for_update=True)
		create_donation.assert_not_called()

	def test_worker_skips_schedule_advanced_after_candidate_query(self) -> None:
		candidate = frappe._dict(name="REC-TEST")
		recurring = Mock(status="Active", next_date="2026-08-01")
		with (
			patch.object(frappe, "get_all", return_value=[candidate]),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=recurring,
			),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(frappe.db, "commit") as commit,
		):
			process_recurring_donations()

		rollback.assert_called_once_with()
		commit.assert_not_called()
		recurring._get_or_create_current_donation.assert_not_called()
		recurring.advance_next_date.assert_not_called()

	def test_worker_advances_observed_installment_once(self) -> None:
		candidate = frappe._dict(name="REC-TEST")
		recurring = Mock(status="Active", next_date="2026-07-01")
		with (
			patch.object(frappe, "get_all", return_value=[candidate]),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=recurring,
			),
			patch.object(frappe.db, "commit") as commit,
		):
			process_recurring_donations()

		recurring._get_or_create_current_donation.assert_called_once_with()
		recurring.advance_next_date.assert_called_once_with()
		recurring.save.assert_called_once_with(ignore_permissions=True)
		commit.assert_called_once_with()

	def test_manual_flow_acts_on_complete_locking_read(self) -> None:
		stale = RecurringDonation({"doctype": "Recurring Donation", "name": "REC-TEST"})
		current = Mock()
		current._get_or_create_current_donation.return_value = Mock(name="DON-CURRENT")
		current._get_or_create_current_donation.return_value.name = "DON-CURRENT"
		with patch(
			"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
			return_value=current,
		) as lock:
			result = stale.create_next_donation()

		self.assertEqual(result, "DON-CURRENT")
		lock.assert_called_once_with("REC-TEST")
		current.check_permission.assert_called_once_with("write")
		current._get_or_create_current_donation.assert_called_once_with()
		current.advance_next_date.assert_called_once_with()
		current.save.assert_called_once_with()
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func[RecurringDonation.create_next_donation],
			["POST"],
		)


class TestRecurringDonationConcurrency(IntegrationTestCase):
	def test_two_workers_create_one_due_installment(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The row-lock regression targets MariaDB/InnoDB")

		token = frappe.generate_hash(length=8)
		donor_type = f"Recurring Race Type {token}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type}).insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Recurring Race Donor {token}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)
		company = (
			frappe.db.get_single_value("Non Profit Settings", "donation_company")
			or frappe.db.get_single_value("Non Profit Settings", "company")
			or frappe.db.get_value("Company", {}, "name", order_by="name asc")
		)
		currency = frappe.db.get_value("Company", company, "default_currency")
		due_date = frappe.utils.getdate("2026-07-01")
		recurring = frappe.get_doc(
			{
				"doctype": "Recurring Donation",
				"donor": donor.name,
				"company": company,
				"amount": 25,
				"currency": currency,
				"frequency": "Monthly",
				"start_date": due_date,
				"next_date": due_date,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		try:
			barrier = Barrier(2)
			with ThreadPoolExecutor(max_workers=2) as executor:
				results = list(
					executor.map(
						_run_concurrent_recurring_installment,
						[frappe.local.site, frappe.local.site],
						[recurring.name, recurring.name],
						[due_date, due_date],
						[barrier, barrier],
					)
				)

			self.assertEqual(sorted(results), ["created", "skipped"])
			self.assertEqual(
				frappe.db.count(
					"Donation",
					{
						"recurring_donation": recurring.name,
						"date": due_date,
						"docstatus": ["<", 2],
					},
				),
				1,
			)
			recurring.reload()
			self.assertEqual(recurring.next_date, frappe.utils.add_months(due_date, 1))
		finally:
			frappe.db.rollback()
			for donation_name in frappe.get_all(
				"Donation",
				filters={"recurring_donation": recurring.name},
				pluck="name",
			):
				donation = frappe.get_doc("Donation", donation_name)
				if donation.docstatus == 1:
					donation.cancel()
				frappe.delete_doc("Donation", donation_name, ignore_permissions=True)
			if frappe.db.exists("Recurring Donation", recurring.name):
				frappe.delete_doc("Recurring Donation", recurring.name, ignore_permissions=True)
			if frappe.db.exists("Donor", donor.name):
				frappe.delete_doc("Donor", donor.name, ignore_permissions=True)
			if frappe.db.exists("Donor Type", donor_type):
				frappe.delete_doc("Donor Type", donor_type, ignore_permissions=True)
			frappe.db.commit()


def _run_concurrent_recurring_installment(
	site: str,
	recurring_name: str,
	due_date,
	barrier: Barrier,
) -> str:
	from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
		_process_due_recurring_donation,
	)

	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		barrier.wait(timeout=30)
		donation_name = _process_due_recurring_donation(recurring_name, due_date)
		if not donation_name:
			frappe.db.rollback()
			return "skipped"
		frappe.db.commit()
		return "created"
	finally:
		frappe.destroy()
