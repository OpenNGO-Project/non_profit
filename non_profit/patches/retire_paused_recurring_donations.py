"""`Paused` is gone from Recurring Donation.

It only ever meant "stop generating installments without ending the
instruction". No payment provider offers a pause, and with the fan-out now
gated there is nothing left that could honour it.

Existing rows move to `Cancelled` — the direction that keeps generation
stopped. Resuming them would start creating donations for people who were
deliberately paused, so the reversible mistake is preferred to the expensive
one, and each row is annotated so staff can tell what happened.
"""

import frappe


def execute():
	if not frappe.db.has_column("Recurring Donation", "status"):
		return

	paused = frappe.get_all("Recurring Donation", filters={"status": "Paused"}, pluck="name")
	if not paused:
		return

	for name in paused:
		frappe.db.set_value("Recurring Donation", name, "status", "Cancelled", update_modified=False)
		frappe.get_doc("Recurring Donation", name).add_comment(
			"Comment",
			"Status 'Paused' was retired and this schedule was set to Cancelled. "
			"Create a new schedule to resume giving.",
		)
