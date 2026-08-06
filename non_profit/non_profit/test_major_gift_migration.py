from types import SimpleNamespace
from unittest.mock import call, patch

from frappe.tests import UnitTestCase

from non_profit.patches import simplify_major_gifts, sync_major_gift_task_donors


class TestMajorGiftMigration(UnitTestCase):
	def test_removed_stages_have_deterministic_targets(self) -> None:
		self.assertEqual(
			simplify_major_gifts.STAGE_RENAMES,
			{"Identification": "Qualification", "Stewardship": "Solicitation"},
		)

	def test_all_interaction_linked_tasks_are_deleted(self) -> None:
		with (
			patch.object(simplify_major_gifts.frappe.db, "table_exists", return_value=True),
			patch.object(simplify_major_gifts.frappe.db, "has_column", return_value=True),
			patch.object(simplify_major_gifts.frappe, "get_all", return_value=["TASK-1", "TASK-2"]),
			patch.object(simplify_major_gifts.frappe, "delete_doc") as delete_doc,
		):
			simplify_major_gifts._delete_interaction_tasks()

		self.assertEqual(
			delete_doc.call_args_list,
			[
				call("Task", "TASK-1", force=True, ignore_missing=True),
				call("Task", "TASK-2", force=True, ignore_missing=True),
			],
		)

	def test_major_gift_task_donors_are_backfilled(self) -> None:
		tasks = [
			SimpleNamespace(name="TASK-1", major_gift="GIFT-1", donor="DONOR-OLD"),
			SimpleNamespace(name="TASK-2", major_gift="GIFT-2", donor="DONOR-2"),
		]
		gifts = [
			SimpleNamespace(name="GIFT-1", donor="DONOR-1"),
			SimpleNamespace(name="GIFT-2", donor="DONOR-2"),
		]
		with (
			patch.object(sync_major_gift_task_donors.frappe, "get_all", side_effect=[tasks, gifts]),
			patch.object(sync_major_gift_task_donors.frappe.db, "set_value") as set_value,
		):
			donors = sync_major_gift_task_donors._sync_task_donors()

		set_value.assert_called_once_with("Task", "TASK-1", "donor", "DONOR-1", update_modified=False)
		self.assertEqual(donors, {"DONOR-1", "DONOR-2", "DONOR-OLD"})
