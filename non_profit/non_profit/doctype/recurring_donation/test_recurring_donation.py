from unittest.mock import Mock, patch

import frappe
from frappe.tests import UnitTestCase

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
			patch.object(frappe.db, "get_value", return_value="DON-TEST"),
			patch.object(frappe, "get_doc", return_value=existing),
			patch.object(recurring, "create_donation") as create_donation,
		):
			result = recurring._get_or_create_current_donation()

		self.assertIs(result, existing)
		create_donation.assert_not_called()

	def test_worker_skips_schedule_advanced_after_candidate_query(self) -> None:
		candidate = frappe._dict(name="REC-TEST", next_date="2026-07-01")
		recurring = Mock(status="Active", next_date="2026-08-01")
		with (
			patch.object(frappe, "get_all", return_value=[candidate]),
			patch.object(frappe, "get_doc", return_value=recurring),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation"
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
		candidate = frappe._dict(name="REC-TEST", next_date="2026-07-01")
		recurring = Mock(status="Active", next_date="2026-07-01")
		with (
			patch.object(frappe, "get_all", return_value=[candidate]),
			patch.object(frappe, "get_doc", return_value=recurring),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation"
			),
			patch.object(frappe.db, "commit") as commit,
		):
			process_recurring_donations()

		recurring._get_or_create_current_donation.assert_called_once_with()
		recurring.advance_next_date.assert_called_once_with()
		recurring.save.assert_called_once_with(ignore_permissions=True)
		commit.assert_called_once_with()
