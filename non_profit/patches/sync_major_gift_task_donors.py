"""Backfill Task.donor from linked Major Gifts and finish retired metadata cleanup."""

import frappe


def execute() -> None:
	from non_profit.non_profit.next_actions import refresh_next_action
	from non_profit.setup import make_custom_fields

	make_custom_fields()
	for donor in sorted(_sync_task_donors()):
		refresh_next_action("Donor", donor)
	frappe.db.delete("Custom DocPerm", {"parent": "Donor Interaction"})


def _sync_task_donors() -> set[str]:
	tasks = frappe.get_all(
		"Task",
		filters={"major_gift": ["is", "set"]},
		fields=["name", "major_gift", "donor"],
		order_by="name asc",
	)
	if not tasks:
		return set()

	gift_donors = {
		row.name: row.donor
		for row in frappe.get_all(
			"Major Gift",
			filters={"name": ["in", [task.major_gift for task in tasks]]},
			fields=["name", "donor"],
		)
	}
	affected_donors = {donor for donor in gift_donors.values() if donor}
	for task in tasks:
		donor = gift_donors.get(task.major_gift)
		if donor and task.donor != donor:
			if task.donor:
				affected_donors.add(task.donor)
			frappe.db.set_value("Task", task.name, "donor", donor, update_modified=False)
	return affected_donors
