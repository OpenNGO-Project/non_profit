from unittest.mock import call, patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.utils import before_tests, ensure_test_selling_defaults


class TestBeforeTestsSafety(UnitTestCase):
	def test_before_tests_does_not_delete_or_rename_shared_records(self) -> None:
		with (
			patch.object(frappe, "get_list", return_value=[frappe._dict(name="Existing Company")]),
			patch("non_profit.non_profit.utils.use_short_test_host_name"),
			patch.object(frappe.db, "get_single_value", return_value="Configured"),
			patch("non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures"),
			patch.object(frappe.db, "delete", side_effect=AssertionError("global delete")),
			patch.object(frappe, "rename_doc", side_effect=AssertionError("global rename")),
			patch.object(frappe.db, "set_single_value", side_effect=AssertionError("global setting")),
		):
			before_tests()

	def test_missing_test_selling_defaults_use_existing_leaf_records(self) -> None:
		with (
			patch.object(frappe.db, "get_single_value", return_value=None),
			patch.object(frappe.db, "get_value", side_effect=("Individual", "United States")),
			patch.object(frappe.db, "set_single_value") as set_single_value,
		):
			ensure_test_selling_defaults()

		self.assertEqual(
			set_single_value.call_args_list,
			[
				call("Selling Settings", "customer_group", "Individual"),
				call("Selling Settings", "territory", "United States"),
			],
		)
