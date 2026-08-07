from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from non_profit.non_profit.doctype.recurring_donation.recurring_donation import (
	PROVIDER_STATUS_MAP,
	RecurringDonation,
	find_by_provider_reference,
	find_by_provider_subscription,
	process_recurring_donations,
)
from non_profit.patches import retire_paused_recurring_donations


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
		recurring = Mock(status="Active", next_date="2026-08-01", is_provider_managed=False)
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
		recurring = Mock(status="Active", next_date="2026-07-01", is_provider_managed=False)
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
		current = Mock(is_provider_managed=False)
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
		candidate = frappe._dict(name="REC-PROVIDER")
		recurring = Mock(status="Active", next_date="2026-07-01", is_provider_managed=True)
		with (
			patch.object(frappe, "get_all", return_value=[candidate]),
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
		):
			self.assertEqual(schedule.retire_abandoned_pending_mandate(), "Cancelled")

		db_set.assert_called_once_with("status", "Cancelled")
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
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(RecurringDonation, "create_donation", return_value="DON-NEW") as create,
			patch.object(RecurringDonation, "db_set"),
		):
			schedule.record_provider_installment(transaction_id="txn-1")

		self.assertTrue(create.call_args.kwargs["mark_paid"])
