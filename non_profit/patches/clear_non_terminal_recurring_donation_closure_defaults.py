import frappe

BATCH_SIZE = 100
CONTAMINATED_CATEGORY = "Donor"
CONTAMINATED_REASON = "Donor requested cancellation"
TERMINAL_STATUSES = ("Payment Failed", "Cancelled")


def execute() -> None:
	if not all(
		frappe.db.has_column("Recurring Donation", fieldname)
		for fieldname in ("closure_category", "closure_reason")
	):
		return

	last_name = ""
	while True:
		filters = {
			"status": ["not in", list(TERMINAL_STATUSES)],
			"closure_category": CONTAMINATED_CATEGORY,
			"closure_reason": CONTAMINATED_REASON,
		}
		if last_name:
			filters["name"] = [">", last_name]
		names = frappe.get_all(
			"Recurring Donation",
			filters=filters,
			pluck="name",
			order_by="name asc",
			limit_page_length=BATCH_SIZE,
		)
		if not names:
			break
		for name in names:
			frappe.db.set_value(
				"Recurring Donation",
				name,
				{"closure_category": None, "closure_reason": None},
				update_modified=False,
			)
		last_name = names[-1]
