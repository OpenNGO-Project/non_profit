import frappe
from frappe.utils import cstr

BATCH_SIZE = 100


def execute() -> None:
	if not frappe.db.has_column("Recurring Donation", "closure_reason"):
		return
	last_name = ""
	while True:
		filters = {"status": ["in", ["Payment Failed", "Cancelled"]]}
		if last_name:
			filters["name"] = [">", last_name]
		rows = frappe.get_all(
			"Recurring Donation",
			filters=filters,
			fields=[
				"name",
				"status",
				"closure_category",
				"closure_reason",
				"closure_details",
				"closed_on",
				"closed_by",
				"last_failure_on",
				"last_decline_reason",
				"modified",
				"modified_by",
			],
			order_by="name asc",
			limit_page_length=BATCH_SIZE,
		)
		if not rows:
			break
		for row in rows:
			if row.closure_category and row.closure_reason and row.closed_on and row.closed_by:
				continue
			category, reason, details = _historical_closure(row)
			frappe.db.set_value(
				"Recurring Donation",
				row.name,
				{
					"closure_category": row.closure_category or category,
					"closure_reason": row.closure_reason or reason,
					"closure_details": row.closure_details or details,
					"closed_on": row.closed_on or row.last_failure_on or row.modified,
					"closed_by": row.closed_by or row.modified_by or "Administrator",
				},
				update_modified=False,
			)
		last_name = rows[-1].name


def _historical_closure(row) -> tuple[str, str, str | None]:
	if row.status == "Payment Failed":
		return "Provider", "Provider final payment failure", cstr(row.last_decline_reason).strip() or None
	if frappe.db.exists(
		"Comment",
		{
			"reference_doctype": "Recurring Donation",
			"reference_name": row.name,
			"content": ["like", "%Status 'Paused' was retired%"],
		},
	):
		return "Migration", "Paused status retired", "Backfilled from the retired Paused status."
	if frappe.db.exists(
		"Comment",
		{
			"reference_doctype": "Recurring Donation",
			"reference_name": row.name,
			"content": ["like", "%Abandoned Pending Mandate retired%"],
		},
	):
		return "Provider", "Abandoned mandate retired", "Backfilled from provider-verified retirement."
	return (
		"Historical",
		"Historical terminal state",
		"Backfilled from a terminal row without structured closure evidence.",
	)
