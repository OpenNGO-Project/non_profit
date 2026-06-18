import frappe


def execute():
	if not frappe.db.exists("DocType", "Donor") or not frappe.db.has_column("Donor", "total_lifetime_amount"):
		return

	from non_profit.non_profit.major_gifts import recompute_all_donor_giving

	recompute_all_donor_giving()
