from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.utils import before_tests


class TestBeforeTestsSafety(UnitTestCase):
	def test_before_tests_does_not_delete_or_rename_shared_records(self) -> None:
		with (
			patch.object(frappe, "get_list", return_value=[frappe._dict(name="Existing Company")]),
			patch("non_profit.non_profit.utils.use_short_test_host_name"),
			patch("non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures"),
			patch.object(frappe.db, "delete", side_effect=AssertionError("global delete")),
			patch.object(frappe, "rename_doc", side_effect=AssertionError("global rename")),
			patch.object(frappe.db, "set_single_value", side_effect=AssertionError("global setting")),
		):
			before_tests()
