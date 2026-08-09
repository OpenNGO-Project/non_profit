from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, add_months, getdate, nowdate

from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
	PROVIDER_STATUS_MAP,
	RecurringDonation,
	find_by_provider_reference,
	find_by_provider_subscription,
	process_recurring_donations,
)
from non_profit.non_profit.recurring_reconciliation import (
	reconcile_recurring_donation,
	record_recurring_installment_reversal,
)
from non_profit.patches import (
	clear_incomplete_recurring_installment_reversal_defaults,
	clear_non_terminal_recurring_donation_closure_defaults,
	retire_paused_recurring_donations,
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
		recurring = Mock(status="Active", next_date="2026-08-01", is_provider_managed=False)
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-TEST"], []]),
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
		recurring = Mock(status="Active", next_date="2026-07-01", is_provider_managed=False)
		recurring.close_if_next_date_is_past_end.return_value = False
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-TEST"], []]),
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
		current = Mock(is_provider_managed=False)
		current.close_if_next_date_is_past_end.return_value = False
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

	def test_manual_flow_closes_past_end_before_creating(self) -> None:
		stale = RecurringDonation({"doctype": "Recurring Donation", "name": "REC-TEST"})
		current = Mock(is_provider_managed=False, status="Cancelled")
		current.close_if_next_date_is_past_end.return_value = True
		with patch(
			"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
			return_value=current,
		):
			self.assertEqual(stale.create_next_donation(), "Cancelled")

		current._get_or_create_current_donation.assert_not_called()
		current.advance_next_date.assert_not_called()

	def test_worker_closes_past_end_before_creating(self) -> None:
		recurring = Mock(
			name="REC-TEST",
			status="Active",
			next_date="2026-07-01",
			is_provider_managed=False,
		)
		recurring.close_if_next_date_is_past_end.return_value = True
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-TEST"], []]),
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

		recurring.close_if_next_date_is_past_end.assert_called_once_with(ignore_permissions=True)
		recurring._get_or_create_current_donation.assert_not_called()
		commit.assert_called_once_with()

	def test_advance_next_date_keeps_the_month_end_anchor(self) -> None:
		# Stepping cumulatively from the previous date turned a Jan-31 monthly
		# schedule into Feb 28, Mar 28, ... — permanently off the day the donor
		# agreed to. Advancing on the start-date anchor recovers Mar 31.
		recurring = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"start_date": "2026-01-31",
				"next_date": "2026-02-28",
				"frequency": "Monthly",
			}
		)
		recurring.advance_next_date()
		self.assertEqual(getdate(recurring.next_date), getdate("2026-03-31"))

	def test_advance_next_date_self_heals_a_drifted_schedule(self) -> None:
		# A schedule that already drifted under the old cumulative stepping
		# (Mar 28 instead of Mar 31) snaps back onto the anchor cadence.
		recurring = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"start_date": "2026-01-31",
				"next_date": "2026-03-28",
				"frequency": "Monthly",
			}
		)
		recurring.advance_next_date()
		self.assertEqual(getdate(recurring.next_date), getdate("2026-04-30"))

	def test_advance_next_date_anchors_quarterly_and_yearly_frequencies(self) -> None:
		quarterly = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"start_date": "2026-01-31",
				"next_date": "2026-04-30",
				"frequency": "Quarterly",
			}
		)
		quarterly.advance_next_date()
		self.assertEqual(getdate(quarterly.next_date), getdate("2026-07-31"))
		leap_yearly = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"start_date": "2024-02-29",
				"next_date": "2025-02-28",
				"frequency": "Yearly",
			}
		)
		leap_yearly.advance_next_date()
		self.assertEqual(getdate(leap_yearly.next_date), getdate("2026-02-28"))

	def test_advance_next_date_without_start_date_stays_on_the_current_cadence(self) -> None:
		recurring = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"next_date": "2026-05-15",
				"frequency": "Monthly",
			}
		)
		recurring.advance_next_date()
		self.assertEqual(getdate(recurring.next_date), getdate("2026-06-15"))

	def test_worker_drains_every_due_page(self) -> None:
		# One fixed page of 100 left day N's overflow to day N+1, and one
		# persistently failing schedule occupied a slot every run. The keyset
		# drain pages until the due set is empty.
		first = Mock(status="Active", next_date="2026-07-01", is_provider_managed=False)
		first.close_if_next_date_is_past_end.return_value = False
		second = Mock(status="Active", next_date="2026-07-01", is_provider_managed=False)
		second.close_if_next_date_is_past_end.return_value = False
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-A"], ["REC-B"], []]) as get_all,
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				side_effect=[first, second],
			) as lock,
			patch.object(frappe.db, "commit"),
		):
			process_recurring_donations()

		self.assertEqual(lock.call_args_list, [call("REC-A"), call("REC-B")])
		self.assertEqual(get_all.call_count, 3)
		self.assertEqual(get_all.call_args_list[1].kwargs["filters"]["name"], [">", "REC-A"])
		self.assertEqual(get_all.call_args_list[2].kwargs["filters"]["name"], [">", "REC-B"])
		first._get_or_create_current_donation.assert_called_once_with()
		second._get_or_create_current_donation.assert_called_once_with()

	def test_worker_drain_terminates_past_a_failing_schedule(self) -> None:
		# A schedule whose processing throws stays due; keyset ordering must
		# move past it rather than refetch it forever, and the Error Log must
		# carry a bounded message, not a recipient-bearing title.
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-FAIL"], []]) as get_all,
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-07-23",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				side_effect=RuntimeError("boom"),
			),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(frappe, "log_error") as log_error,
		):
			process_recurring_donations()

		self.assertEqual(get_all.call_count, 2)
		rollback.assert_called_once_with()
		self.assertEqual(log_error.call_args.kwargs["title"], "Recurring Donation fan-out failed")
		self.assertIn("RuntimeError", log_error.call_args.kwargs["message"])
		self.assertIn("REC-FAIL", log_error.call_args.kwargs["message"])


class TestExpectedDateAnchoring(UnitTestCase):
	def test_expected_dates_keep_the_month_end_anchor(self) -> None:
		# Cumulative stepping produced Jan 31, Feb 28, Mar 28, Apr 28 — off the
		# provider's charge anchor from March on. Anchored advancement recovers
		# the month-end day whenever the month has it.
		from non_profit.non_profit.recurring_reconciliation import _expected_dates

		schedule = frappe._dict(name="REC-ANCHOR", start_date="2026-01-31", frequency="Monthly")
		self.assertEqual(
			_expected_dates(schedule, getdate("2026-04-30")),
			[getdate("2026-01-31"), getdate("2026-02-28"), getdate("2026-03-31"), getdate("2026-04-30")],
		)

	def test_expected_dates_anchor_quarterly_and_leap_yearly(self) -> None:
		from non_profit.non_profit.recurring_reconciliation import _expected_dates

		quarterly = frappe._dict(name="REC-Q", start_date="2026-01-31", frequency="Quarterly")
		self.assertEqual(
			_expected_dates(quarterly, getdate("2026-08-01")),
			[getdate("2026-01-31"), getdate("2026-04-30"), getdate("2026-07-31")],
		)
		leap_yearly = frappe._dict(name="REC-Y", start_date="2024-02-29", frequency="Yearly")
		self.assertEqual(
			_expected_dates(leap_yearly, getdate("2026-03-01")),
			[getdate("2024-02-29"), getdate("2025-02-28"), getdate("2026-02-28")],
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
			donation_names = frappe.get_all(
				"Donation",
				filters={"recurring_donation": recurring.name},
				pluck="name",
			)
			for donation_name in donation_names:
				donation = frappe.get_doc("Donation", donation_name)
				if donation.docstatus == 1:
					donation.cancel()
			if frappe.db.exists("Recurring Donation", recurring.name):
				frappe.delete_doc(
					"Recurring Donation",
					recurring.name,
					force=True,
					ignore_permissions=True,
				)
			for donation_name in donation_names:
				frappe.db.set_value(
					"Donation",
					donation_name,
					"recurring_donation",
					None,
					update_modified=False,
				)
				frappe.delete_doc("Donation", donation_name, ignore_permissions=True)
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


class TestProviderBackedSchedules(UnitTestCase):
	"""A schedule the provider charges must never also be charged by us."""

	@staticmethod
	def _schedule(**values) -> RecurringDonation:
		return RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-PROVIDER",
				"payment_provider": "Payrexx",
				"provider_subscription_id": "42",
				"provider_reference": "IR-1",
				"provider_account": "Live",
				**values,
			}
		)

	def test_provider_link_needs_all_parts_but_any_provider_state_blocks_local_fan_out(self):
		self.assertTrue(self._schedule().is_provider_backed)
		self.assertFalse(self._schedule(provider_subscription_id="").is_provider_backed)
		self.assertFalse(self._schedule(payment_provider="").is_provider_backed)
		self.assertTrue(self._schedule(provider_subscription_id="").is_provider_managed)
		self.assertTrue(self._schedule(payment_provider="").is_provider_managed)

	def test_scheduler_query_excludes_provider_backed_schedules(self):
		"""The filter is the reason double installments are impossible."""
		with (
			patch.object(frappe, "get_all", return_value=[]) as get_all,
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-08-07",
			),
		):
			process_recurring_donations()

		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["payment_provider"], ["in", ["", None]])

	def test_incomplete_provider_schedule_is_excluded_from_local_fan_out(self):
		"""The provider owns the mandate before its first event supplies an id."""
		recurring = Mock(status="Active", next_date="2026-07-01", is_provider_managed=True)
		with patch(
			"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
			return_value=recurring,
		):
			from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
				_process_due_recurring_donation,
			)

			self.assertIsNone(_process_due_recurring_donation("REC-PENDING", frappe.utils.getdate()))
		recurring._get_or_create_current_donation.assert_not_called()

	def test_worker_re_checks_provider_ownership_under_the_lock(self):
		"""The filter can go stale between the candidate query and the lock."""
		recurring = Mock(status="Active", next_date="2026-07-01", is_provider_managed=True)
		with (
			patch.object(frappe, "get_all", side_effect=[["REC-PROVIDER"], []]),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.nowdate",
				return_value="2026-08-07",
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=recurring,
			),
			patch.object(frappe.db, "rollback"),
			patch.object(frappe.db, "commit") as commit,
		):
			process_recurring_donations()

		recurring._get_or_create_current_donation.assert_not_called()
		commit.assert_not_called()

	def test_manual_installment_is_refused_on_a_provider_backed_schedule(self):
		"""Generating one by hand would invent money that never moved."""
		stale = self._schedule()
		with patch(
			"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
			return_value=self._schedule(),
		):
			with self.assertRaises(frappe.ValidationError):
				stale.create_next_donation()

	def test_provider_managed_financial_terms_cannot_be_changed_by_ordinary_save(self):
		schedule = self._schedule(amount=75, currency="CHF", frequency="Monthly", status="Active")
		before = self._schedule(amount=50, currency="CHF", frequency="Monthly", status="Active")
		with (
			patch.object(schedule, "get_doc_before_save", return_value=before),
			patch.object(schedule, "has_value_changed", side_effect=lambda field: field == "amount"),
			self.assertRaises(frappe.ValidationError),
		):
			schedule.validate()


class TestProviderStatusMapping(UnitTestCase):
	def test_terminal_closure_audit_is_immutable(self):
		schedule = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-1",
				"status": "Cancelled",
				"closure_category": "Donor",
				"closure_reason": "Donor requested cancellation",
				"closure_details": "changed",
				"closed_on": "2026-08-09 10:00:00",
				"closed_by": "Administrator",
			}
		)
		before = RecurringDonation(schedule.as_dict())
		before.closure_details = "original"
		with (
			patch.object(schedule, "get_doc_before_save", return_value=before),
			patch.object(
				schedule,
				"has_value_changed",
				side_effect=lambda fieldname: fieldname == "closure_details",
			),
			self.assertRaisesRegex(frappe.ValidationError, "cannot be changed"),
		):
			schedule._validate_terminal_closure()

	def test_first_terminal_transition_overwrites_caller_supplied_audit_identity(self):
		schedule = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"status": "Cancelled",
				"closure_category": "Donor",
				"closure_reason": "Donor requested cancellation",
				"closed_on": "2000-01-01 00:00:00",
				"closed_by": "forged@example.org",
			}
		)
		with (
			patch.object(schedule, "get_doc_before_save", return_value=None),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation.now_datetime",
				return_value="2026-08-09 12:00:00",
			),
			patch.object(frappe, "session", frappe._dict(user="actual@example.org")),
		):
			schedule._validate_terminal_closure()

		self.assertEqual(schedule.closed_on, "2026-08-09 12:00:00")
		self.assertEqual(schedule.closed_by, "actual@example.org")

	def test_every_provider_state_maps_somewhere(self):
		self.assertEqual(
			PROVIDER_STATUS_MAP,
			{
				"active": "Active",
				"overdue": "Payment Retrying",
				"failed": "Payment Failed",
				"in_notice": "Ending",
				"cancelled": "Cancelled",
			},
		)

	def test_retrying_and_failed_stay_distinct(self):
		"""Collapsing them makes staff chase donors who are about to pay."""
		self.assertNotEqual(PROVIDER_STATUS_MAP["overdue"], PROVIDER_STATUS_MAP["failed"])

	def test_ending_still_collects(self):
		"""The donor gave notice; the remaining charges still arrive."""
		from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
			COLLECTING_STATUSES,
		)

		self.assertIn(PROVIDER_STATUS_MAP["in_notice"], COLLECTING_STATUSES)
		self.assertNotIn(PROVIDER_STATUS_MAP["cancelled"], COLLECTING_STATUSES)
		self.assertNotIn(PROVIDER_STATUS_MAP["failed"], COLLECTING_STATUSES)

	def test_apply_status_mirrors_the_providers_next_charge_date(self):
		schedule = RecurringDonation({"doctype": "Recurring Donation", "name": "REC-1", "status": "Active"})
		with patch.object(RecurringDonation, "db_set") as db_set:
			schedule.apply_provider_status("overdue", next_payment="2026-09-01")

		updates = db_set.call_args.args[0]
		self.assertEqual(updates["status"], "Payment Retrying")
		# next_date is a mirror once the provider owns the schedule; letting the
		# two disagree would make reports contradict each other.
		self.assertEqual(str(updates["next_date"]), "2026-09-01")
		self.assertEqual(str(updates["provider_next_payment"]), "2026-09-01")

	def test_final_provider_failure_records_structured_closure(self):
		schedule = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-1",
				"status": "Active",
				"last_decline_reason": "card expired",
			}
		)
		with (
			patch.object(RecurringDonation, "db_set") as db_set,
			patch("non_profit.non_profit.doctype.recurring_donation.recurring_donation.notify"),
		):
			schedule.apply_provider_status("failed")

		updates = db_set.call_args.args[0]
		self.assertEqual(updates["status"], "Payment Failed")
		self.assertEqual(updates["closure_category"], "Provider")
		self.assertEqual(updates["closure_reason"], "Provider final payment failure")
		self.assertEqual(updates["closure_details"], "card expired")
		self.assertTrue(updates["closed_on"])
		self.assertTrue(updates["closed_by"])

	def test_unknown_provider_status_changes_nothing(self):
		schedule = RecurringDonation({"doctype": "Recurring Donation", "name": "REC-1", "status": "Active"})
		with patch.object(RecurringDonation, "db_set") as db_set:
			self.assertIsNone(schedule.apply_provider_status("something-new"))
		db_set.assert_not_called()

	def test_cancelled_and_failed_states_are_terminal(self):
		for status in ("Cancelled", "Payment Failed"):
			with self.subTest(status=status):
				schedule = RecurringDonation(
					{"doctype": "Recurring Donation", "name": "REC-1", "status": status}
				)
				with (
					patch.object(RecurringDonation, "db_set") as db_set,
					patch.object(frappe, "log_error") as log_error,
				):
					self.assertIsNone(schedule.apply_provider_status("active", next_payment="2026-09-01"))
				db_set.assert_not_called()
				log_error.assert_called_once()

	def test_duplicate_terminal_status_does_not_mutate_next_payment(self):
		schedule = RecurringDonation(
			{"doctype": "Recurring Donation", "name": "REC-1", "status": "Cancelled"}
		)
		with patch.object(RecurringDonation, "db_set") as db_set:
			self.assertEqual(
				schedule.apply_provider_status("cancelled", next_payment="2026-09-01"),
				"Cancelled",
			)
		db_set.assert_not_called()

	def test_retry_success_may_return_to_active(self):
		schedule = RecurringDonation(
			{"doctype": "Recurring Donation", "name": "REC-1", "status": "Payment Retrying"}
		)
		with patch.object(RecurringDonation, "db_set") as db_set:
			self.assertEqual(schedule.apply_provider_status("active"), "Active")
		self.assertEqual(db_set.call_args.args[0]["status"], "Active")


class TestProviderInstallmentRecording(UnitTestCase):
	@staticmethod
	def _schedule() -> RecurringDonation:
		return RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-PROVIDER",
				"payment_provider": "Payrexx",
				"provider_subscription_id": "42",
				"amount": 50,
			}
		)

	def test_a_replayed_charge_reuses_the_existing_donation(self):
		"""Provider webhooks retry for days; each real payment arrives many times."""
		schedule = self._schedule()
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe.db, "get_value", return_value="DON-1") as get_value,
			patch.object(frappe, "get_doc", return_value="existing") as get_doc,
			patch.object(RecurringDonation, "create_donation") as create,
		):
			result = schedule.record_provider_installment(transaction_id="txn-1")

		self.assertEqual(result, "existing")
		create.assert_not_called()
		get_doc.assert_called_once_with("Donation", "DON-1", for_update=True)
		# Keyed on the provider transaction, not the date: two charges inside one
		# period are two installments, ten deliveries of one are not.
		self.assertEqual(get_value.call_args.args[1]["payment_id"], "txn-1")
		self.assertNotIn("docstatus", get_value.call_args.args[1])

	def test_replay_after_cancelled_donation_never_creates_duplicate_accounting(self):
		"""Cancelled evidence still consumes the provider transaction id."""
		schedule = self._schedule()
		cancelled = Mock(name="cancelled donation", docstatus=2)
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe.db, "get_value", return_value="DON-CANCELLED"),
			patch.object(frappe, "get_doc", return_value=cancelled),
			patch.object(RecurringDonation, "create_donation") as create,
		):
			result = schedule.record_provider_installment(transaction_id="txn-cancelled")

		self.assertIs(result, cancelled)
		create.assert_not_called()

	def test_a_new_charge_creates_a_paid_donation_carrying_the_transaction_id(self):
		schedule = self._schedule()
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(RecurringDonation, "create_donation", return_value="DON-NEW") as create,
			patch.object(RecurringDonation, "db_set") as db_set,
		):
			result = schedule.record_provider_installment(
				transaction_id="txn-2", paid_on="2026-08-07", amount=75
			)

		self.assertEqual(result, "DON-NEW")
		self.assertTrue(create.call_args.kwargs["mark_paid"])
		self.assertEqual(create.call_args.kwargs["payment_id"], "txn-2")
		self.assertEqual(create.call_args.kwargs["amount"], 75)
		self.assertEqual(str(create.call_args.kwargs["date"]), "2026-08-07")
		# A successful charge clears the failure state.
		self.assertEqual(db_set.call_args.args[0]["failure_count"], 0)

	def test_paid_installment_uses_donation_authorization_state_machine(self):
		schedule = self._schedule()
		donation = Mock()
		with patch.object(frappe, "get_doc", return_value=donation):
			self.assertIs(schedule.create_donation(mark_paid=True, payment_id="txn-paid"), donation)

		donation.insert.assert_called_once_with()
		donation.submit.assert_called_once_with()
		donation.run_method.assert_called_once_with("on_payment_authorized", "Completed", payment_date=None)
		donation.db_set.assert_not_called()

	def test_a_charge_without_a_transaction_id_is_refused(self):
		"""Without it there is no idempotency key, so replays would duplicate money."""
		with self.assertRaises(frappe.ValidationError):
			self._schedule().record_provider_installment(transaction_id="  ")

	def test_non_provider_schedule_cannot_record_provider_installment(self):
		schedule = RecurringDonation({"doctype": "Recurring Donation", "name": "REC-LOCAL", "amount": 50})
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			self.assertRaisesRegex(frappe.ValidationError, "provider-managed"),
		):
			schedule.record_provider_installment(transaction_id="txn-local")

	def test_provider_installment_cannot_override_standard_donation_fields(self):
		schedule = self._schedule()
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			self.assertRaisesRegex(frappe.ValidationError, "Custom Fields"),
		):
			schedule.record_provider_installment(
				transaction_id="txn-forged",
				donation_values={"donor": "OTHER-DONOR"},
			)

	def test_provider_installment_accepts_value_bearing_custom_field_decorations(self):
		from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
			_provider_installment_donation_values,
		)

		field = frappe._dict(is_custom_field=1, fieldtype="Data")
		meta = frappe._dict(get_field=lambda fieldname: field if fieldname == "custom_marker" else None)
		with patch.object(frappe, "get_meta", return_value=meta):
			self.assertEqual(
				_provider_installment_donation_values({"custom_marker": "provider evidence"}),
				{"custom_marker": "provider evidence"},
			)


class TestProviderOperationDispatch(UnitTestCase):
	@staticmethod
	def _schedule(**values) -> RecurringDonation:
		return RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-PROVIDER",
				"payment_provider": "Payrexx",
				"provider_subscription_id": "42",
				"provider_reference": "IR-1",
				"provider_account": "Live",
				"status": "Active",
				"amount": 50,
				"currency": "CHF",
				**values,
			}
		)

	def test_unclaimed_provider_action_fails_loudly(self):
		"""Silently doing nothing leaves the donor charged the old amount."""
		schedule = self._schedule()
		with (
			patch.object(RecurringDonation, "check_permission"),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe, "get_hooks", return_value=[]),
			self.assertRaises(frappe.ValidationError),
		):
			schedule.change_amount(80)

	def test_cancelling_a_cancelled_schedule_is_a_no_op(self):
		schedule = self._schedule(status="Cancelled")
		with (
			patch.object(RecurringDonation, "check_permission"),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe, "get_hooks", return_value=[]) as get_hooks,
		):
			self.assertEqual(schedule.cancel_schedule(), "Cancelled")
		get_hooks.assert_not_called()

	def test_cancelling_any_terminal_schedule_is_a_no_op(self):
		schedule = self._schedule(status="Payment Failed")
		with (
			patch.object(RecurringDonation, "check_permission"),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe, "get_hooks", return_value=[]) as get_hooks,
			patch.object(schedule, "db_set") as db_set,
		):
			self.assertEqual(schedule.cancel_schedule(), "Payment Failed")
		get_hooks.assert_not_called()
		db_set.assert_not_called()

	def test_amount_change_is_refused_once_the_schedule_stopped_collecting(self):
		schedule = self._schedule(status="Cancelled")
		with (
			patch.object(RecurringDonation, "check_permission"),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			self.assertRaises(frappe.ValidationError),
		):
			schedule.change_amount(80)

	def test_provider_cancel_preflights_reconciliation_before_external_dispatch(self):
		schedule = self._schedule()
		with (
			patch.object(RecurringDonation, "check_permission"),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._reconcile_schedule",
				side_effect=frappe.ValidationError("unsafe local state"),
			),
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._dispatch_provider"
			) as dispatch,
			self.assertRaisesRegex(frappe.ValidationError, "unsafe local state"),
		):
			schedule.cancel_schedule()
		dispatch.assert_not_called()

	def test_provider_operations_are_post_only(self):
		for method in (
			RecurringDonation.change_amount,
			RecurringDonation.cancel_schedule,
			RecurringDonation.retire_abandoned_pending_mandate,
		):
			with self.subTest(method=method.__name__):
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"])

	def test_abandoned_pending_mandate_requires_positive_provider_proof(self):
		schedule = self._schedule(status="Pending Mandate", provider_subscription_id="")
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(schedule, "check_permission"),
			patch.object(frappe, "get_hooks", return_value=["provider.verify"]),
			patch.object(
				frappe,
				"get_attr",
				return_value=lambda **_kwargs: {"safe_to_retire": True, "provider_status": "expired"},
			),
			patch.object(schedule, "db_set") as db_set,
			patch.object(schedule, "add_comment") as add_comment,
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._reconcile_schedule"
			) as reconcile,
		):
			self.assertEqual(schedule.retire_abandoned_pending_mandate(), "Cancelled")

		updates = db_set.call_args.args[0]
		self.assertEqual(updates["status"], "Cancelled")
		self.assertEqual(updates["closure_reason"], "Abandoned mandate retired")
		reconcile.assert_called_once_with(schedule)
		add_comment.assert_called_once()

	def test_abandoned_pending_mandate_stays_open_without_provider_proof(self):
		schedule = self._schedule(status="Pending Mandate", provider_subscription_id="")
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(schedule, "check_permission"),
			patch.object(frappe, "get_hooks", return_value=["provider.verify"]),
			patch.object(
				frappe,
				"get_attr",
				return_value=lambda **_kwargs: {"safe_to_retire": False},
			),
			patch.object(schedule, "db_set") as db_set,
			self.assertRaises(frappe.ValidationError),
		):
			schedule.retire_abandoned_pending_mandate()
		db_set.assert_not_called()

	def test_incomplete_provider_state_fails_closed_for_supported_actions(self):
		incomplete = self._schedule(provider_subscription_id="")
		for method, args in (("change_amount", (80,)), ("cancel_schedule", ())):
			with (
				self.subTest(method=method),
				patch(
					"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
					return_value=incomplete,
				),
				patch.object(incomplete, "check_permission"),
				self.assertRaises(frappe.ValidationError),
			):
				getattr(incomplete, method)(*args)

	def test_permission_is_checked_on_the_current_locked_schedule(self):
		stale = self._schedule()
		current = self._schedule()
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=current,
			),
			patch.object(current, "check_permission", side_effect=frappe.PermissionError) as permission,
			self.assertRaises(frappe.PermissionError),
		):
			stale.cancel_schedule()
		permission.assert_called_once_with("write")


class TestProviderSubscriptionLookup(UnitTestCase):
	def test_ambiguity_is_refused_rather_than_guessed(self):
		"""Two schedules claiming one subscription would attach money arbitrarily."""
		with (
			patch.object(frappe, "get_all", return_value=["REC-A", "REC-B"]),
			patch.object(frappe, "log_error") as log_error,
		):
			self.assertIsNone(find_by_provider_subscription("Payrexx", "42", "Live"))
		log_error.assert_called_once()

	def test_a_single_match_resolves(self):
		with patch.object(frappe, "get_all", return_value=["REC-A"]) as get_all:
			self.assertEqual(find_by_provider_subscription("Payrexx", "42", "Live"), "REC-A")
			filters = get_all.call_args.kwargs["filters"]
		# A subscription id is only unique within one provider account, so the
		# account is part of the key rather than a detail.
		self.assertEqual(filters["provider_account"], "Live")

	def test_no_match_is_none(self):
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(find_by_provider_subscription("Payrexx", "42", "Live"))

	def test_provider_reference_lookup_uses_the_exact_provider_account_and_request(self):
		with patch.object(frappe, "get_all", return_value=["REC-A"]) as get_all:
			self.assertEqual(find_by_provider_reference("Payrexx", "IR-123", "Live"), "REC-A")
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(
			filters,
			{
				"payment_provider": "Payrexx",
				"provider_reference": "IR-123",
				"provider_account": "Live",
			},
		)


class TestRetirePausedRecurringDonations(UnitTestCase):
	def test_paused_schedule_is_cancelled_with_timeline_evidence(self) -> None:
		schedule = Mock()
		with (
			patch.object(retire_paused_recurring_donations.frappe.db, "has_column", return_value=True),
			patch.object(retire_paused_recurring_donations.frappe, "get_all", return_value=["REC-PAUSED"]),
			patch.object(retire_paused_recurring_donations.frappe.db, "set_value") as set_value,
			patch.object(retire_paused_recurring_donations.frappe, "get_doc", return_value=schedule),
		):
			retire_paused_recurring_donations.execute()

		set_value.assert_called_once_with(
			"Recurring Donation",
			"REC-PAUSED",
			"status",
			"Cancelled",
			update_modified=False,
		)
		schedule.add_comment.assert_called_once()
		self.assertIn("Create a new schedule", schedule.add_comment.call_args.args[1])


class TestScheduleCurrencyDefault(UnitTestCase):
	def test_currency_defaults_to_the_company_currency_not_a_global_guess(self):
		"""It used to fall back to EUR while the deployments using it are Swiss."""
		schedule = RecurringDonation(
			{"doctype": "Recurring Donation", "name": "REC-1", "company": "_Test NPO", "donor": None}
		)
		with patch.object(frappe, "get_cached_value", return_value="CHF"):
			schedule.validate()
		self.assertEqual(schedule.currency, "CHF")

	def test_currency_must_equal_company_default(self):
		schedule = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-1",
				"company": "_Test NPO",
				"currency": "EUR",
			}
		)
		with (
			patch.object(frappe, "get_cached_value", return_value="CHF"),
			self.assertRaisesRegex(frappe.ValidationError, "must match Company"),
		):
			schedule.validate()

	def test_installment_backfill_reports_legacy_currency_mismatch_before_writing(self):
		from non_profit.patches import backfill_recurring_donation_installments as backfill

		with (
			patch.object(
				backfill.frappe,
				"get_all",
				side_effect=[
					[frappe._dict(name="GoodNPO", default_currency="CHF")],
					[frappe._dict(name="REC-EUR", company="GoodNPO", currency="EUR")],
					[],
				],
			),
			self.assertRaisesRegex(frappe.ValidationError, "REC-EUR.*EUR / CHF"),
		):
			backfill._assert_company_currency_compatibility()


class TestRecurringDonationReconciliation(IntegrationTestCase):
	def test_closure_selects_have_explicit_blank_defaults(self) -> None:
		meta = frappe.get_meta("Recurring Donation")
		schedule = frappe.new_doc("Recurring Donation")

		for fieldname in ("closure_category", "closure_reason"):
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertEqual(field.default, "")
				self.assertEqual(field.options.split("\n", 1)[0], "")
				self.assertEqual(schedule.get(fieldname), "")

	def test_default_contamination_patch_preserves_terminal_evidence(self) -> None:
		with open(frappe.get_app_path("non_profit", "patches.txt")) as patches_file:
			post_model_patches = patches_file.read().split("[post_model_sync]", 1)[1]
		self.assertIn(
			"non_profit.patches.clear_non_terminal_recurring_donation_closure_defaults",
			post_model_patches,
		)

		contaminated = self._schedule(start_date=nowdate(), amount=25)
		other_non_terminal = self._schedule(start_date=nowdate(), amount=25)
		terminal = self._schedule(start_date=nowdate(), amount=25)
		frappe.db.set_value(
			"Recurring Donation",
			contaminated.name,
			{
				"closure_category": "Donor",
				"closure_reason": "Donor requested cancellation",
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"Recurring Donation",
			other_non_terminal.name,
			{
				"closure_category": "Administrative",
				"closure_reason": "Administrative closure",
			},
			update_modified=False,
		)
		terminal_evidence = {
			"status": "Cancelled",
			"closure_category": "Donor",
			"closure_reason": "Donor requested cancellation",
			"closure_details": "Verified donor request",
			"closed_on": frappe.utils.get_datetime("2026-08-09 10:00:00"),
			"closed_by": "Administrator",
		}
		frappe.db.set_value(
			"Recurring Donation",
			terminal.name,
			terminal_evidence,
			update_modified=False,
		)

		clear_non_terminal_recurring_donation_closure_defaults.execute()
		clear_non_terminal_recurring_donation_closure_defaults.execute()

		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation",
				contaminated.name,
				["closure_category", "closure_reason"],
			),
			(None, None),
		)
		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation",
				other_non_terminal.name,
				["closure_category", "closure_reason"],
			),
			("Administrative", "Administrative closure"),
		)
		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation",
				terminal.name,
				list(terminal_evidence),
				as_dict=True,
			),
			terminal_evidence,
		)

	def test_installment_reversal_selects_have_explicit_blank_defaults(self) -> None:
		meta = frappe.get_meta("Recurring Donation Installment")
		installment = frappe.new_doc("Recurring Donation Installment")

		for fieldname in ("reversal_source", "reversal_kind"):
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertEqual(field.default, "")
				self.assertEqual(field.options.split("\n", 1)[0], "")
				self.assertEqual(installment.get(fieldname), "")

	def test_reversal_default_cleanup_preserves_partial_and_complete_evidence(self) -> None:
		from non_profit.non_profit.recurring_reconciliation import (
			record_recurring_installment_reversal,
		)

		with open(frappe.get_app_path("non_profit", "patches.txt")) as patches_file:
			post_model_patches = patches_file.read().split("[post_model_sync]", 1)[1]
		self.assertIn(
			"non_profit.patches.clear_incomplete_recurring_installment_reversal_defaults",
			post_model_patches,
		)

		contaminated_schedule = self._schedule(start_date=nowdate(), amount=25)
		partial_schedule = self._schedule(start_date=nowdate(), amount=25)
		complete_schedule = self._schedule(start_date=nowdate(), amount=25)
		contaminated = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": contaminated_schedule.name},
			"name",
		)
		partial = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": partial_schedule.name},
			"name",
		)
		frappe.db.set_value(
			"Recurring Donation Installment",
			contaminated,
			{
				"reversal_source": "Accounting",
				"reversal_kind": "Payment Entry Cancellation",
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"Recurring Donation Installment",
			partial,
			{
				"reversal_source": "Accounting",
				"reversal_kind": "Payment Entry Cancellation",
				"reversal_reference": "REVIEW-PARTIAL-EVIDENCE",
			},
			update_modified=False,
		)

		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": complete_schedule.donor,
				"company": complete_schedule.company,
				"date": nowdate(),
				"amount": 25,
				"paid": 1,
				"recurring_donation": complete_schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		reversal = record_recurring_installment_reversal(
			donation.name,
			reversal_kind="Payment Entry Cancellation",
			reversal_reference="PE-COMPLETE-EVIDENCE",
			reversal_date=nowdate(),
			reversal_amount=25,
		)
		complete_before = frappe.db.get_value(
			"Recurring Donation Installment",
			reversal["installment"],
			[
				"status",
				"reversal_source",
				"reversal_kind",
				"reversal_reference",
				"reversal_date",
				"reversal_amount",
				"reversal_recorded_on",
			],
			as_dict=True,
		)
		self.assertEqual(reversal["status"], "Reversed")
		self.assertEqual(complete_before.status, "Reversed")
		self.assertEqual(complete_before.reversal_source, "Accounting")
		self.assertEqual(complete_before.reversal_kind, "Payment Entry Cancellation")
		self.assertEqual(complete_before.reversal_reference, "PE-COMPLETE-EVIDENCE")
		self.assertEqual(complete_before.reversal_date, getdate(nowdate()))
		self.assertEqual(complete_before.reversal_amount, 25)
		self.assertTrue(complete_before.reversal_recorded_on)

		clear_incomplete_recurring_installment_reversal_defaults.execute()
		clear_incomplete_recurring_installment_reversal_defaults.execute()

		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				contaminated,
				["reversal_source", "reversal_kind"],
			),
			(None, None),
		)
		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				partial,
				["reversal_source", "reversal_kind", "reversal_reference"],
			),
			("Accounting", "Payment Entry Cancellation", "REVIEW-PARTIAL-EVIDENCE"),
		)
		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				reversal["installment"],
				list(complete_before),
				as_dict=True,
			),
			complete_before,
		)

	def test_paid_amount_variance_links_the_actual_donation(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=50)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": nowdate(),
				"amount": 40,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		installment = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "installment_kind": "Expected"},
			["status", "donation", "expected_amount", "actual_amount", "amount_variance"],
			as_dict=True,
		)
		self.assertEqual(installment.status, "Variance")
		self.assertEqual(installment.donation, donation.name)
		self.assertEqual(installment.expected_amount, 50)
		self.assertEqual(installment.actual_amount, 40)
		self.assertEqual(installment.amount_variance, -10)

	def test_past_unsettled_expectation_is_missed(self) -> None:
		schedule = self._schedule(start_date=add_months(nowdate(), -1), amount=25)
		missed = frappe.get_all(
			"Recurring Donation Installment",
			filters={"recurring_donation": schedule.name, "status": "Missed"},
			pluck="name",
		)
		self.assertEqual(len(missed), 1)

	def test_daily_reconciliation_keeps_the_future_next_installment_active(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		future_date = add_months(nowdate(), 1)
		frappe.db.set_value(
			"Recurring Donation", schedule.name, "next_date", future_date, update_modified=False
		)
		reconcile_recurring_donation(schedule.name, through_date=future_date)
		reconcile_recurring_donation(schedule.name)

		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "expected_date": future_date},
				"is_retired",
			),
			0,
		)

	def test_historical_reversal_does_not_move_the_reconciliation_clock_back(self) -> None:
		start_date = add_months(nowdate(), -2)
		schedule = self._schedule(start_date=start_date, amount=25)
		reconcile_recurring_donation(schedule.name, through_date=nowdate())
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": start_date,
				"amount": 25,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		record_recurring_installment_reversal(
			donation.name,
			reversal_kind="Full Refund",
			reversal_reference="HISTORICAL-REFUND",
			reversal_date=start_date,
			reversal_amount=25,
		)

		current_rows = frappe.get_all(
			"Recurring Donation Installment",
			filters={
				"recurring_donation": schedule.name,
				"expected_date": [">", start_date],
			},
			fields=["status", "is_retired"],
			order_by="expected_date asc",
		)
		self.assertTrue(current_rows)
		self.assertTrue(all(not row.is_retired for row in current_rows))
		self.assertTrue(all(row.status == "Missed" for row in current_rows[:-1]))

	def test_pre_16_18_month_end_settlement_is_remapped_and_rerun_safe(self) -> None:
		schedule = self._schedule(start_date=getdate("2026-01-31"), amount=25)
		self._paid_donation(schedule, "2026-01-31")
		self._paid_donation(schedule, "2026-02-28")
		march_donation = self._paid_donation(schedule, "2026-03-28")
		legacy_name = self._make_legacy_march_installment(schedule, march_donation)

		for _index in range(2):
			reconcile_recurring_donation(
				schedule.name,
				as_of="2026-04-01",
				through_date="2026-04-01",
			)

		anchored = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "expected_date": "2026-03-31"},
			[
				"name",
				"status",
				"donation",
				"actual_date",
				"actual_amount",
				"is_retired",
			],
			as_dict=True,
		)
		legacy = frappe.db.get_value(
			"Recurring Donation Installment",
			legacy_name,
			[
				"status",
				"expected_date",
				"donation",
				"actual_date",
				"actual_amount",
				"is_retired",
			],
			as_dict=True,
		)
		self.assertEqual(anchored.status, "Settled")
		self.assertEqual(anchored.donation, march_donation.name)
		self.assertEqual(anchored.actual_date, getdate("2026-03-28"))
		self.assertEqual(anchored.actual_amount, 25)
		self.assertFalse(anchored.is_retired)
		self.assertEqual(legacy.status, "Cancelled")
		self.assertEqual(legacy.expected_date, getdate("2026-03-28"))
		self.assertFalse(legacy.donation)
		self.assertFalse(legacy.actual_date)
		self.assertFalse(legacy.actual_amount)
		self.assertTrue(legacy.is_retired)
		self.assertEqual(
			frappe.db.count(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "donation": march_donation.name},
			),
			1,
		)

		schedule.reload()
		self.assertEqual(schedule.expected_installment_count, 3)
		self.assertEqual(schedule.actual_installment_count, 3)
		self.assertEqual(schedule.missed_installment_count, 0)
		self.assertEqual(schedule.variance_installment_count, 0)
		self.assertEqual(schedule.due_expected_amount, 75)
		self.assertEqual(schedule.settled_actual_amount, 75)
		self.assertEqual(schedule.settlement_variance, 0)
		with open(frappe.get_app_path("non_profit", "patches.txt")) as patches_file:
			self.assertIn(
				"non_profit.patches.repair_anchored_recurring_installment_evidence",
				patches_file.read().split("[post_model_sync]", 1)[1],
			)

	def test_anchored_rebuild_fails_before_writing_ambiguous_legacy_evidence(self) -> None:
		schedule = self._schedule(start_date=getdate("2026-01-31"), amount=25)
		self._paid_donation(schedule, "2026-01-31")
		self._paid_donation(schedule, "2026-02-28")
		march_donations = [
			self._paid_donation(schedule, "2026-03-28"),
			self._paid_donation(schedule, "2026-03-28"),
		]
		for index, donation in enumerate(march_donations):
			self._make_legacy_march_installment(
				schedule,
				donation,
				delete_anchored=index == 0,
			)

		before = frappe.get_all(
			"Recurring Donation Installment",
			filters={"recurring_donation": schedule.name},
			fields=[
				"name",
				"installment_kind",
				"expected_date",
				"donation",
				"actual_date",
				"actual_amount",
				"is_retired",
			],
			order_by="name asc",
		)
		with self.assertRaisesRegex(frappe.ValidationError, "ambiguous legacy installment evidence"):
			reconcile_recurring_donation(
				schedule.name,
				as_of="2026-04-01",
				through_date="2026-04-01",
			)
		self.assertEqual(
			frappe.get_all(
				"Recurring Donation Installment",
				filters={"recurring_donation": schedule.name},
				fields=list(before[0]),
				order_by="name asc",
			),
			before,
		)

	def test_anchored_rebuild_duplicate_targets_write_nothing(self) -> None:
		schedule, _donation, _legacy_name = self._anchored_remap_fixture()
		target = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "expected_date": "2026-03-31"},
			["status", "expected_amount", "currency", "is_retired", "retired_on"],
			as_dict=True,
		)
		duplicate = frappe.get_doc(
			{
				"doctype": "Recurring Donation Installment",
				"recurring_donation": schedule.name,
				"installment_kind": "Expected",
				"expected_date": "2026-03-31",
				**target,
			}
		)
		from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
			allow_reconciliation_write,
		)

		allow_reconciliation_write(duplicate)
		duplicate.insert(ignore_permissions=True)

		self._assert_anchored_rebuild_rejected_without_writes(
			schedule,
			"ambiguous anchored installments",
		)

	def test_anchored_rebuild_target_with_evidence_writes_nothing(self) -> None:
		schedule, donation, _legacy_name = self._anchored_remap_fixture()
		target = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "expected_date": "2026-03-31"},
			"name",
		)
		frappe.db.set_value(
			"Recurring Donation Installment",
			target,
			{
				"donation": donation.name,
				"actual_date": donation.date,
				"actual_amount": donation.amount,
			},
			update_modified=False,
		)

		self._assert_anchored_rebuild_rejected_without_writes(
			schedule,
			"conflicting installment evidence",
		)

	def test_anchored_rebuild_partial_or_malformed_actual_evidence_writes_nothing(self) -> None:
		cases = {
			"partial actual snapshot": {"actual_date": None},
			"nonpositive actual amount": {"actual_amount": -25},
		}
		for label, updates in cases.items():
			with self.subTest(label=label):
				schedule, _donation, legacy_name = self._anchored_remap_fixture()
				frappe.db.set_value(
					"Recurring Donation Installment",
					legacy_name,
					updates,
					update_modified=False,
				)
				self._assert_anchored_rebuild_rejected_without_writes(
					schedule,
					"incomplete legacy installment evidence",
				)

	def test_anchored_rebuild_partial_or_malformed_reversal_evidence_writes_nothing(self) -> None:
		cases = {
			"partial reversal": {"reversal_source": "Accounting"},
			"source and kind mismatch": {
				"reversal_source": "Accounting",
				"reversal_kind": "Full Refund",
				"reversal_reference": "MALFORMED-REVERSAL",
				"reversal_date": "2026-03-29",
				"reversal_amount": 25,
				"reversal_recorded_on": "2026-03-29 10:00:00",
			},
		}
		for label, updates in cases.items():
			with self.subTest(label=label):
				schedule, _donation, legacy_name = self._anchored_remap_fixture()
				frappe.db.set_value(
					"Recurring Donation Installment",
					legacy_name,
					updates,
					update_modified=False,
				)
				self._assert_anchored_rebuild_rejected_without_writes(
					schedule,
					"incomplete legacy reversal evidence",
				)

	def test_natural_end_keeps_the_final_generated_installment_active(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		schedule.end_date = nowdate()
		schedule.save(ignore_permissions=True)

		donation_name = schedule.create_next_donation()
		schedule.reload()
		self.assertEqual(schedule.closure_reason, "End date reached")
		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "donation": donation_name},
				"status",
			),
			"Expected",
		)

	def test_cancelled_unpaid_donation_is_not_reversed_actual_evidence(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": nowdate(),
				"amount": 25,
				"paid": 0,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		donation.cancel()

		installments = frappe.get_all(
			"Recurring Donation Installment",
			filters={"recurring_donation": schedule.name},
			fields=["installment_kind", "status", "actual_amount"],
		)
		self.assertFalse(any(row.status == "Reversed" for row in installments))
		self.assertFalse(any(row.installment_kind == "Unexpected" for row in installments))
		self.assertFalse(any(row.actual_amount for row in installments))

	def test_late_payment_matches_latest_unfilled_due_expectation(self) -> None:
		start_date = add_months(nowdate(), -2)
		schedule = self._schedule(start_date=start_date, amount=25)
		paid_on = add_days(add_months(start_date, 1), 10)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": paid_on,
				"amount": 25,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()

		expected_date = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "donation": donation.name},
			"expected_date",
		)
		self.assertEqual(expected_date, getdate(add_months(start_date, 1)))

	def test_donation_cancellation_does_not_forge_reversal_evidence(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		donations = []
		for _index in range(2):
			donation = frappe.get_doc(
				{
					"doctype": "Donation",
					"donor": schedule.donor,
					"company": schedule.company,
					"date": nowdate(),
					"amount": 25,
					"paid": 1,
					"recurring_donation": schedule.name,
				}
			).insert(ignore_permissions=True)
			donation.submit()
			donations.append(donation)

		unexpected = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "donation": donations[1].name},
			["installment_kind", "status"],
			as_dict=True,
		)
		self.assertEqual(unexpected.installment_kind, "Unexpected")
		self.assertEqual(unexpected.status, "Unexpected")

		donations[1].cancel()
		installment = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "donation": donations[1].name},
			["status", "actual_amount", "reversal_kind", "reversal_reference"],
			as_dict=True,
		)
		self.assertEqual(installment.status, "Unexpected")
		self.assertEqual(installment.actual_amount, 25)
		self.assertFalse(installment.reversal_kind)
		self.assertFalse(installment.reversal_reference)

	def test_conflicting_reversal_is_not_accepted_as_an_idempotent_replay(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": nowdate(),
				"amount": 25,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		record_recurring_installment_reversal(
			donation.name,
			reversal_kind="Full Refund",
			reversal_reference="REFUND-EVENT-1",
			reversal_date=nowdate(),
			reversal_amount=25,
		)

		from non_profit.non_profit.recurring_reconciliation import RecurringReversalMismatchError

		# Terminal mismatches carry the typed error so provider apps can keep
		# the event as review evidence instead of retrying it forever.
		with self.assertRaisesRegex(RecurringReversalMismatchError, "conflicts with existing"):
			record_recurring_installment_reversal(
				donation.name,
				reversal_kind="Chargeback",
				reversal_reference="CHARGEBACK-EVENT-2",
				reversal_date=nowdate(),
				reversal_amount=25,
			)

		with self.assertRaisesRegex(RecurringReversalMismatchError, "Only a full"):
			record_recurring_installment_reversal(
				donation.name,
				reversal_kind="Full Refund",
				reversal_reference="REFUND-EVENT-PARTIAL",
				reversal_date=nowdate(),
				reversal_amount=10,
			)

	def test_original_actual_snapshot_cannot_be_rewritten(self) -> None:
		from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
			allow_reconciliation_write,
		)

		schedule = self._schedule(start_date=nowdate(), amount=25)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": nowdate(),
				"amount": 25,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		installment_name = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "donation": donation.name},
			"name",
		)
		installment = frappe.get_doc("Recurring Donation Installment", installment_name)
		installment.actual_amount = 30
		allow_reconciliation_write(installment)

		with self.assertRaisesRegex(frappe.ValidationError, "accounting evidence cannot be changed"):
			installment.save(ignore_permissions=True)

	def test_final_failure_marks_closure_day_expectation_missed(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		with patch("non_profit.non_profit.doctype.recurring_donation.recurring_donation.notify"):
			schedule.apply_provider_status("failed")

		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "expected_date": nowdate()},
				"status",
			),
			"Missed",
		)

	def test_cancellation_marks_expectations_cancelled_from_effective_date(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		with patch("non_profit.non_profit.doctype.recurring_donation.recurring_donation.notify"):
			schedule.cancel_schedule()

		self.assertEqual(
			frappe.db.get_value(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "expected_date": nowdate()},
				"status",
			),
			"Cancelled",
		)

	def test_cadence_change_retires_and_reactivates_obsolete_expectations(self) -> None:
		start_date = add_months(nowdate(), -2)
		schedule = self._schedule(start_date=start_date, amount=25)

		schedule.frequency = "Quarterly"
		schedule.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.count(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "installment_kind": "Expected", "is_retired": 1},
			),
			2,
		)
		schedule.reload()
		self.assertEqual(schedule.expected_installment_count, 1)

		schedule.frequency = "Monthly"
		schedule.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.count(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "installment_kind": "Expected", "is_retired": 1},
			),
			0,
		)

	def test_installment_cannot_be_written_outside_reconciliation(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Recurring Donation Installment",
					"recurring_donation": schedule.name,
					"installment_kind": "Expected",
					"status": "Expected",
					"expected_date": nowdate(),
					"expected_amount": 25,
					"currency": schedule.currency,
				}
			).insert(ignore_permissions=True)

	def test_installment_cannot_be_deleted_outside_parent_cascade(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		installment = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name},
			"name",
		)

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Recurring Donation Installment", installment, ignore_permissions=True)

	def test_deleting_schedule_cascades_guarded_installment_rows(self) -> None:
		schedule = self._schedule(start_date=nowdate(), amount=25)
		installment = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name},
			"name",
		)

		frappe.delete_doc("Recurring Donation", schedule.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Recurring Donation Installment", installment))

	def _anchored_remap_fixture(self):
		schedule = self._schedule(start_date=getdate("2026-01-31"), amount=25)
		self._paid_donation(schedule, "2026-01-31")
		self._paid_donation(schedule, "2026-02-28")
		march_donation = self._paid_donation(schedule, "2026-03-28")
		legacy_name = self._make_legacy_march_installment(
			schedule,
			march_donation,
			delete_anchored=False,
		)
		return schedule, march_donation, legacy_name

	def _assert_anchored_rebuild_rejected_without_writes(self, schedule, message: str) -> None:
		before = self._anchored_rebuild_state(schedule)
		with self.assertRaisesRegex(frappe.ValidationError, message):
			reconcile_recurring_donation(
				schedule.name,
				as_of="2026-04-01",
				through_date="2026-04-01",
			)
		self.assertEqual(self._anchored_rebuild_state(schedule), before)

	@staticmethod
	def _anchored_rebuild_state(schedule) -> dict:
		return {
			"schedule": frappe.db.get_value(
				"Recurring Donation",
				schedule.name,
				[
					"expected_installment_count",
					"actual_installment_count",
					"missed_installment_count",
					"variance_installment_count",
					"due_expected_amount",
					"settled_actual_amount",
					"settlement_variance",
					"last_reconciled_on",
					"modified",
				],
				as_dict=True,
			),
			"installments": frappe.get_all(
				"Recurring Donation Installment",
				filters={"recurring_donation": schedule.name},
				fields=[
					"name",
					"installment_kind",
					"status",
					"expected_date",
					"expected_amount",
					"currency",
					"is_retired",
					"retired_on",
					"donation",
					"actual_date",
					"actual_amount",
					"amount_variance",
					"reversal_source",
					"reversal_kind",
					"reversal_reference",
					"reversal_date",
					"reversal_amount",
					"reversal_recorded_on",
					"reconciled_on",
					"modified",
				],
				order_by="name asc",
			),
		}

	def _paid_donation(self, schedule, donation_date):
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": schedule.donor,
				"company": schedule.company,
				"date": donation_date,
				"amount": schedule.amount,
				"paid": 1,
				"recurring_donation": schedule.name,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		return donation

	def _make_legacy_march_installment(self, schedule, donation, *, delete_anchored=True) -> str:
		from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
			allow_reconciliation_write,
		)

		if delete_anchored:
			anchored_name = frappe.db.get_value(
				"Recurring Donation Installment",
				{"recurring_donation": schedule.name, "expected_date": "2026-03-31"},
				"name",
			)
			anchored = frappe.get_doc("Recurring Donation Installment", anchored_name)
			allow_reconciliation_write(anchored)
			anchored.delete(ignore_permissions=True, delete_permanently=True)

		legacy_name = frappe.db.get_value(
			"Recurring Donation Installment",
			{"recurring_donation": schedule.name, "donation": donation.name},
			"name",
		)
		legacy = frappe.get_doc("Recurring Donation Installment", legacy_name)
		self.assertEqual(legacy.installment_kind, "Unexpected")
		legacy.update(
			{
				"installment_kind": "Expected",
				"expected_date": "2026-03-28",
				"expected_amount": schedule.amount,
				"status": "Settled",
			}
		)
		allow_reconciliation_write(legacy)
		legacy.save(ignore_permissions=True)
		return legacy.name

	def _schedule(self, *, start_date, amount):
		donor_type = frappe.db.get_value("Donor Type", {}, "name")
		if not donor_type:
			donor_type = (
				frappe.get_doc(
					{
						"doctype": "Donor Type",
						"donor_type": f"_Test Recurring {frappe.generate_hash(length=8)}",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"_Test Recurring {frappe.generate_hash(length=8)}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)
		company = (
			frappe.db.get_single_value("Non Profit Settings", "donation_company")
			or frappe.db.get_single_value("Non Profit Settings", "company")
			or frappe.db.get_value("Company", {}, "name", order_by="name asc")
		)
		return frappe.get_doc(
			{
				"doctype": "Recurring Donation",
				"donor": donor.name,
				"company": company,
				"amount": amount,
				"frequency": "Monthly",
				"start_date": start_date,
				"next_date": start_date,
				"status": "Active",
			}
		).insert(ignore_permissions=True)


class TestInstallmentsQualifyForTaxReceipts(UnitTestCase):
	"""A provider installment must be an ordinary Donation in every downstream sense.

	The annual Bescheinigung aggregates submitted, paid Donations. Installments
	are created submitted and paid, so they qualify without a special case — but
	that is a property worth pinning, because losing it would silently understate
	every monthly donor's yearly receipt.
	"""

	def test_the_receipt_filter_matches_what_an_installment_looks_like(self):
		from non_profit.non_profit.tax_receipts import _qualifying_donations

		captured = {}

		def fake_get_list(_doctype, **kwargs):
			captured.update(kwargs)
			return []

		with (
			patch.object(frappe, "get_list", side_effect=fake_get_list),
			patch.object(frappe, "get_all", return_value=[]),
		):
			_qualifying_donations("Test NPO", 2026)

		filters = captured["filters"]
		# Exactly the state record_provider_installment leaves a Donation in.
		self.assertEqual(filters["docstatus"], 1)
		self.assertEqual(filters["paid"], 1)
		# Nothing excludes recurring installments, and nothing should.
		self.assertNotIn("recurring_donation", filters)
		self.assertNotIn("payment_id", filters)

	def test_an_installment_is_created_submitted_and_paid(self):
		schedule = RecurringDonation(
			{
				"doctype": "Recurring Donation",
				"name": "REC-PROVIDER",
				"payment_provider": "Payrexx",
				"provider_subscription_id": "42",
				"amount": 50,
			}
		)
		with (
			patch(
				"non_profit.non_profit.doctype.recurring_donation.recurring_donation._lock_recurring_donation",
				return_value=schedule,
			),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(RecurringDonation, "create_donation", return_value="DON-NEW") as create,
			patch.object(RecurringDonation, "db_set"),
		):
			schedule.record_provider_installment(transaction_id="txn-1")

		self.assertTrue(create.call_args.kwargs["mark_paid"])
