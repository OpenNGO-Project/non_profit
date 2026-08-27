from unittest.mock import call, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from non_profit.non_profit.utils import (
	before_tests,
	ensure_test_selling_defaults,
	reserve_erpnext_standard_price_lists,
)


class TestBeforeTestsSafety(UnitTestCase):
	def test_before_tests_does_not_delete_or_rename_shared_records(self) -> None:
		with (
			patch.object(frappe, "get_list", return_value=[frappe._dict(name="Existing Company")]),
			patch("non_profit.non_profit.utils.use_short_test_host_name"),
			# Patched for the same reason as the host-name call above: this
			# test runs before_tests almost fully mocked, and the reservation
			# reads and writes the database. Its own behaviour is covered by
			# TestStandardPriceListReservation below.
			patch("non_profit.non_profit.utils.reserve_erpnext_standard_price_lists"),
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


class TestStandardPriceListReservation(IntegrationTestCase):
	"""ERPNext's test bootstrap must find these, not try to create them.

	``erpnext.tests.utils`` de-duplicates Standard Buying / Standard Selling on
	a filter that includes ``currency: "INR"``. Anything else and it inserts,
	and the insert dies on a primary-key duplicate because Price List autonames
	from ``price_list_name``.
	"""

	def test_standard_price_lists_match_what_erpnext_looks_for(self) -> None:
		reserve_erpnext_standard_price_lists()

		for price_list_name, buying, selling in (
			("Standard Buying", 1, 0),
			("Standard Selling", 0, 1),
		):
			self.assertTrue(
				frappe.db.exists(
					"Price List",
					{
						"price_list_name": price_list_name,
						"enabled": 1,
						"buying": buying,
						"selling": selling,
						"currency": "INR",
					},
				),
				f"{price_list_name} would collide with ERPNext's test bootstrap",
			)

	def test_reservation_is_idempotent(self) -> None:
		before = frappe.db.count("Price List")
		reserve_erpnext_standard_price_lists()
		reserve_erpnext_standard_price_lists()
		self.assertEqual(frappe.db.count("Price List"), before)
