import frappe


def execute() -> None:
	if not frappe.db.has_column("Household", "total_lifetime_amount"):
		return
	from non_profit.non_profit.household_giving import recompute_all_household_giving

	recompute_all_household_giving()
