"""Donor notices for a recurring instruction."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit import recurring_notices
from non_profit.non_profit.doctype.recurring_donation.recurring_donation import RecurringDonation


def _schedule(**values):
	return frappe._dict(
		{
			"name": "NPO-REC-1",
			"email": "donor@example.test",
			"donor_name": "Anna Muster",
			"amount": 50,
			"currency": "CHF",
			"frequency": "Monthly",
			**values,
		}
	)


class TestRecurringNotices(UnitTestCase):
	def test_each_flow_composes_a_subject_and_body(self):
		for flow in (recurring_notices.SIGNUP, recurring_notices.PAYMENT_FAILED, recurring_notices.CANCELLED):
			with self.subTest(flow=flow):
				subject, message = recurring_notices._compose(_schedule(), flow)
				self.assertTrue(subject)
				self.assertIn("Anna Muster", message)
				self.assertIn("50", message)

	def test_guest_controlled_notice_values_are_html_escaped(self):
		_subject, message = recurring_notices._compose(
			_schedule(
				donor_name='<img src=x onerror="alert(1)">',
				frequency="<b>Monthly</b>",
			),
			recurring_notices.SIGNUP,
		)
		self.assertNotIn("<img", message)
		self.assertNotIn("<b>", message)
		self.assertIn("&lt;img", message)

	def test_an_unknown_flow_is_a_programming_error(self):
		with self.assertRaises(ValueError):
			recurring_notices._compose(_schedule(), "recurring_something_else")

	def test_a_schedule_without_an_email_is_skipped_quietly(self):
		with patch.object(recurring_notices, "send_referenced_email") as send:
			self.assertFalse(recurring_notices.notify(_schedule(email=""), recurring_notices.SIGNUP))
		send.assert_not_called()

	def test_the_notice_is_linked_to_the_schedule_for_the_timeline(self):
		with patch.object(recurring_notices, "send_referenced_email") as send:
			self.assertTrue(recurring_notices.notify(_schedule(), recurring_notices.SIGNUP))
		self.assertEqual(send.call_args.kwargs["reference_doctype"], "Recurring Donation")
		self.assertEqual(send.call_args.kwargs["reference_name"], "NPO-REC-1")

	def test_a_failing_notice_never_undoes_the_event_that_triggered_it(self):
		"""We have already accepted the provider event; the email is secondary."""
		with (
			patch.object(recurring_notices, "send_referenced_email", side_effect=OSError("smtp down")),
			patch.object(frappe, "log_error") as log_error,
		):
			self.assertFalse(recurring_notices.notify(_schedule(), recurring_notices.CANCELLED))
		log_error.assert_called_once()

	def test_database_retry_signals_propagate(self):
		for error in (frappe.QueryDeadlockError("deadlock"), frappe.QueryTimeoutError("timeout")):
			with (
				self.subTest(error=type(error).__name__),
				patch.object(recurring_notices, "send_referenced_email", side_effect=error),
				self.assertRaises(type(error)),
			):
				recurring_notices.notify(_schedule(), recurring_notices.CANCELLED)


class TestNoticeTriggers(UnitTestCase):
	@staticmethod
	def _doc(status: str) -> RecurringDonation:
		return RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "NPO-REC-1",
				"status": status,
				"email": "donor@example.test",
				"amount": 50,
			}
		)

	def _apply(self, from_status: str, provider_status: str):
		schedule = self._doc(from_status)
		with (
			patch.object(RecurringDonation, "db_set"),
			patch("non_profit.non_profit.doctype.recurring_donation.recurring_donation.notify") as notify,
		):
			schedule.apply_provider_status(provider_status)
		return notify

	def test_the_mandate_is_confirmed_when_the_provider_first_reports_active(self):
		notify = self._apply("Pending Mandate", "active")
		self.assertEqual(notify.call_args.args[1], recurring_notices.SIGNUP)

	def test_retrying_says_nothing_to_the_donor(self):
		"""The provider is still trying; a failure mail now would be wrong."""
		notify = self._apply("Active", "overdue")
		notify.assert_not_called()

	def test_a_final_failure_is_announced(self):
		notify = self._apply("Payment Retrying", "failed")
		self.assertEqual(notify.call_args.args[1], recurring_notices.PAYMENT_FAILED)

	def test_cancellation_is_announced(self):
		notify = self._apply("Active", "cancelled")
		self.assertEqual(notify.call_args.args[1], recurring_notices.CANCELLED)

	def test_an_unchanged_status_says_nothing(self):
		"""Provider webhooks repeat for days; each replay must stay silent."""
		notify = self._apply("Active", "active")
		notify.assert_not_called()

	def test_ending_is_not_announced_as_a_stop(self):
		"""The donor gave notice and the remaining charges still follow."""
		notify = self._apply("Active", "in_notice")
		notify.assert_not_called()
