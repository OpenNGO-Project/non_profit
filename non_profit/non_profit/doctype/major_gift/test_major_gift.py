# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

IGNORE_TEST_RECORD_DEPENDENCIES = ["Currency", "Donation Campaign", "Donor", "Task", "User"]


class TestMajorGift(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_won_stage_stamps_closed_date(self) -> None:
		from non_profit.non_profit.major_gifts import advance_major_gift_to_stage

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		advance_major_gift_to_stage(gift, "Won")
		gift.reload()
		self.assertTrue(gift.closed_on)

	def test_interactive_won_transition_requires_reason(self) -> None:
		from non_profit.non_profit.doctype.major_gift.major_gift import apply_outcome_workflow

		gift = self._major_gift(stage="Solicitation", ask_amount=5000)
		gift.flags.ignore_permissions = False
		gift.stage = "Won"

		with self.assertRaisesRegex(frappe.ValidationError, "Won Reason is required"):
			gift.save()

		gift.reload()
		result = apply_outcome_workflow(gift.name, "Mark Won", "The donor accepted the proposal")
		gift.reload()
		self.assertEqual(result["stage"], "Won")
		self.assertEqual(gift.won_reason, "The donor accepted the proposal")
		self.assertFalse(gift.lost_reason)

	def test_interactive_lost_transition_requires_reason(self) -> None:
		from non_profit.non_profit.doctype.major_gift.major_gift import apply_outcome_workflow

		gift = self._major_gift(stage="Qualification", ask_amount=2000)
		gift.flags.ignore_permissions = False
		gift.stage = "Lost"

		with self.assertRaisesRegex(frappe.ValidationError, "Lost Reason is required"):
			gift.save()

		gift.reload()
		result = apply_outcome_workflow(
			gift.name, "Mark Lost", "The request does not fit the donor's priorities"
		)
		gift.reload()
		self.assertEqual(result["stage"], "Lost")
		self.assertEqual(gift.lost_reason, "The request does not fit the donor's priorities")
		self.assertFalse(gift.won_reason)

	def test_outcome_workflow_rejects_unsupported_actions(self) -> None:
		from non_profit.non_profit.doctype.major_gift.major_gift import apply_outcome_workflow

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		with self.assertRaisesRegex(frappe.ValidationError, "Unsupported Major Gift outcome action"):
			apply_outcome_workflow(gift.name, "Solicit", "Ready to ask")

	def test_advance_from_mid_pipeline_stage_moves_forward_only(self) -> None:
		from non_profit.non_profit.major_gifts import advance_major_gift_to_stage

		# A gift already advanced past Qualification must reach a terminal stage
		# without any (illegal, workflow-rejected) backward transition.
		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		self.assertEqual(gift.stage, "Cultivation")

		advance_major_gift_to_stage(gift, "Won")

		gift.reload()
		self.assertEqual(gift.stage, "Won")

	def test_advance_marks_lost_from_early_stage(self) -> None:
		from non_profit.non_profit.major_gifts import advance_major_gift_to_stage

		# Early disqualification: Mark Lost is reachable directly from
		# Qualification (no need to route through Cultivation).
		gift = self._major_gift(stage="Qualification", ask_amount=2000)
		advance_major_gift_to_stage(gift, "Lost")
		gift.reload()
		self.assertEqual(gift.stage, "Lost")
		self.assertTrue(gift.closed_on)

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

	def test_all_record_reconciliation_has_bounded_query_count_and_skips_unchanged_rows(self) -> None:
		from non_profit.non_profit.major_gifts import reconcile_fundraising_rollups

		donor = self._donor()
		self._donation(donor=donor.name, amount=250)
		gift = self._major_gift(stage="Solicitation", ask_amount=1000)
		self._donation(donor=gift.donor, amount=400, major_gift=gift.name)
		reconcile_fundraising_rollups()
		donor_modified = frappe.db.get_value("Donor", donor.name, "modified")
		gift_modified = frappe.db.get_value("Major Gift", gift.name, "modified")

		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			reconcile_fundraising_rollups()

		self.assertLessEqual(sql.call_count, 6)
		self.assertEqual(frappe.db.get_value("Donor", donor.name, "modified"), donor_modified)
		self.assertEqual(frappe.db.get_value("Major Gift", gift.name, "modified"), gift_modified)

	def test_set_next_action_creates_links_and_assigns_task(self) -> None:
		from non_profit.non_profit.next_actions import set_next_action

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		frappe.db.set_value("Major Gift", gift.name, "relationship_manager", "Administrator")

		result = set_next_action("Major Gift", gift.name, "Call the donor", nowdate())

		task = frappe.get_doc("Task", result["task"])
		self.assertEqual(task.subject, "Call the donor")
		self.assertEqual(task.donor, gift.donor)
		self.assertEqual(task.major_gift, gift.name)
		self.assertTrue(
			frappe.db.exists(
				"ToDo",
				{"reference_type": "Task", "reference_name": task.name, "allocated_to": "Administrator"},
			)
		)

		gift.reload()
		self.assertEqual(gift.next_action, "Call the donor")
		self.assertEqual(getdate(gift.next_action_date), getdate(nowdate()))
		self.assertEqual(gift.next_action_task, task.name)
		donor = frappe.get_doc("Donor", gift.donor)
		self.assertEqual(donor.next_action, "Call the donor")
		self.assertEqual(donor.next_action_task, task.name)

	def test_donor_next_action_creates_donor_only_task(self) -> None:
		from non_profit.non_profit.next_actions import set_next_action

		donor = self._donor()
		frappe.db.set_value("Donor", donor.name, "relationship_manager", "Administrator")

		result = set_next_action("Donor", donor.name, "Arrange introductory call", nowdate())

		task = frappe.get_doc("Task", result["task"])
		self.assertEqual(task.donor, donor.name)
		self.assertFalse(task.major_gift)
		donor.reload()
		self.assertEqual(donor.next_action, "Arrange introductory call")
		self.assertEqual(donor.next_action_task, task.name)

	def test_major_gift_task_forces_matching_donor(self) -> None:
		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		other_donor = self._donor()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Review the ask",
				"status": "Open",
				"major_gift": gift.name,
				"donor": other_donor.name,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(task.donor, gift.donor)

	def test_donor_cannot_change_after_task_is_linked(self) -> None:
		from non_profit.non_profit.next_actions import create_next_action_task

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		create_next_action_task("Major Gift", gift.name, "Review the ask")
		gift.donor = self._donor().name

		with self.assertRaisesRegex(frappe.ValidationError, "Donor cannot be changed"):
			gift.save()

	def test_task_writer_needs_major_gift_write_permission(self) -> None:
		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Restricted gift task",
				"status": "Open",
				"major_gift": gift.name,
			}
		).insert(ignore_permissions=True)
		user = self._projects_user()

		frappe.set_user(user.name)
		try:
			task = frappe.get_doc("Task", task.name)
			task.subject = "Unauthorized update"
			with self.assertRaises(frappe.PermissionError):
				task.save()
		finally:
			frappe.set_user("Administrator")

	def test_task_deleter_needs_major_gift_write_permission(self) -> None:
		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Restricted gift task",
				"status": "Open",
				"major_gift": gift.name,
			}
		).insert(ignore_permissions=True)
		user = self._projects_user()

		frappe.set_user(user.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.delete_doc("Task", task.name)
			self.assertTrue(frappe.db.exists("Task", task.name))
		finally:
			frappe.set_user("Administrator")

	def test_next_action_tracks_earliest_open_task_and_completion(self) -> None:
		from non_profit.non_profit.next_actions import create_next_action_task

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		create_next_action_task("Major Gift", gift.name, "Later step", add_days(nowdate(), 10))
		create_next_action_task("Major Gift", gift.name, "Sooner step", add_days(nowdate(), 2))

		gift.reload()
		self.assertEqual(gift.next_action, "Sooner step")
		self.assertEqual(getdate(gift.next_action_date), getdate(add_days(nowdate(), 2)))

		# Completing the earliest task advances the rollup to the next open one.
		sooner_task = frappe.get_doc("Task", gift.next_action_task)
		sooner_task.status = "Completed"
		sooner_task.save(ignore_permissions=True)
		gift.reload()
		self.assertEqual(gift.next_action, "Later step")

	def test_completing_all_tasks_clears_next_action(self) -> None:
		from non_profit.non_profit.next_actions import create_next_action_task

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		create_next_action_task("Major Gift", gift.name, "Only step", nowdate())
		gift.reload()
		task = frappe.get_doc("Task", gift.next_action_task)
		task.status = "Completed"
		task.save(ignore_permissions=True)
		gift.reload()
		self.assertFalse(gift.next_action)
		self.assertFalse(gift.next_action_task)
		self.assertFalse(gift.next_action_date)

	def test_manual_follow_up_date_is_preserved_without_task(self) -> None:
		from non_profit.non_profit.next_actions import refresh_next_action

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		gift.next_action_date = add_days(nowdate(), 5)
		gift.save(ignore_permissions=True)

		refresh_next_action("Major Gift", gift.name)
		gift.reload()
		self.assertEqual(getdate(gift.next_action_date), getdate(add_days(nowdate(), 5)))
		self.assertFalse(gift.next_action_task)

	def test_task_owned_follow_up_date_cannot_be_edited_on_major_gift(self) -> None:
		from non_profit.non_profit.next_actions import create_next_action_task

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		create_next_action_task("Major Gift", gift.name, "Call the donor", add_days(nowdate(), 2))
		gift.reload()
		gift.next_action_date = add_days(nowdate(), 3)

		with self.assertRaisesRegex(frappe.ValidationError, "controlled by the open Next Action Task"):
			gift.save(ignore_permissions=True)

	def test_patch_converts_legacy_next_action(self) -> None:
		from non_profit.patches.convert_next_actions_to_tasks import execute

		gift = self._major_gift(stage="Cultivation", ask_amount=5000)
		# Simulate legacy free-text data (the field is now read-only/derived).
		frappe.db.set_value(
			"Major Gift",
			gift.name,
			{"next_action": "Legacy follow-up", "next_action_date": nowdate()},
			update_modified=False,
		)
		execute()
		gift.reload()
		self.assertTrue(gift.next_action_task)
		task = frappe.get_doc("Task", gift.next_action_task)
		self.assertEqual(task.subject, "Legacy follow-up")
		self.assertEqual(task.major_gift, gift.name)

	# --- helpers -----------------------------------------------------------

	def _major_gift(self, stage: str, ask_amount: float):
		from non_profit.non_profit.major_gifts import advance_major_gift_to_stage

		donor = self._donor()
		gift = frappe.get_doc(
			{
				"doctype": "Major Gift",
				"donor": donor.name,
				"ask_amount": ask_amount,
			}
		).insert(ignore_permissions=True)
		return advance_major_gift_to_stage(gift, stage)

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

	def _projects_user(self):
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": f"gift-task-{frappe.generate_hash(length=8)}@example.com",
				"first_name": "Gift Task User",
				"enabled": 1,
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": "Projects User"}],
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
