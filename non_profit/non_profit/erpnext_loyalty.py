from __future__ import annotations

import frappe

ERP_NEXT_TEST_LOYALTY_PROGRAMS = ("Test Single Loyalty", "Test Multiple Loyalty")


def disable_test_loyalty_auto_opt_in() -> None:
	"""Keep ERPNext test loyalty fixtures from auto-enrolling NPO Customers."""
	if not frappe.db.exists("DocType", "Loyalty Program"):
		return

	for loyalty_program in ERP_NEXT_TEST_LOYALTY_PROGRAMS:
		if not frappe.db.exists("Loyalty Program", loyalty_program):
			continue
		if not frappe.db.get_value("Loyalty Program", loyalty_program, "auto_opt_in"):
			continue
		frappe.db.set_value(
			"Loyalty Program",
			loyalty_program,
			"auto_opt_in",
			0,
			update_modified=False,
		)
