# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Major-gift cultivation helpers.

Donor giving roll-ups, major-donor flagging, and Major Gift pipeline roll-ups.
Kept generic — no client- or presentation-layer assumptions.
"""

from collections import deque

import frappe
from frappe.query_builder.functions import Count, Max, Min, Sum
from frappe.utils import flt, getdate

# Win probability per pipeline stage (percent). ``probability`` is read-only and
# always re-derived from the stage on validate (terminal stages force 100 / 0),
# so it stays in lock-step with the pipeline.
STAGE_PROBABILITY = {
	"Identification": 10,
	"Qualification": 25,
	"Cultivation": 40,
	"Solicitation": 60,
	"Stewardship": 75,
	"Won": 100,
	"Lost": 0,
}

PIPELINE_STAGES = (
	"Identification",
	"Qualification",
	"Cultivation",
	"Solicitation",
	"Stewardship",
)
TERMINAL_STAGES = ("Won", "Lost")


def on_donation_change(doc, method: str | None = None) -> None:
	"""Donation submit/cancel/trash hook.

	Refresh the donor's giving roll-up and any linked Major Gift's closed amount.
	"""
	if doc.get("donor"):
		recompute_donor_giving(doc.donor)
	if doc.get("major_gift"):
		recompute_major_gift_closed(doc.major_gift)


def recompute_donor_giving(donor: str) -> None:
	"""Recompute the stored giving summary on a Donor from its submitted, paid
	Donations and re-derive the major-donor flag."""
	if not donor or not frappe.db.exists("Donor", donor):
		return

	donation = frappe.qb.DocType("Donation")
	total, count, first_date, last_date, largest = (
		frappe.qb.from_(donation)
		.select(
			Sum(donation.amount),
			Count(donation.name),
			Min(donation.date),
			Max(donation.date),
			Max(donation.amount),
		)
		.where(donation.donor == donor)
		.where(donation.docstatus == 1)
		.where(donation.paid == 1)
	).run()[0]

	last_gift_amount = 0.0
	if last_date:
		last_rows = frappe.get_all(
			"Donation",
			filters={"donor": donor, "docstatus": 1, "paid": 1},
			fields=["amount"],
			order_by="date desc, modified desc",
			limit=1,
		)
		if last_rows:
			last_gift_amount = flt(last_rows[0].amount)

	total = flt(total)
	frappe.db.set_value(
		"Donor",
		donor,
		{
			"total_lifetime_amount": total,
			"gift_count": int(count or 0),
			"first_gift_date": getdate(first_date) if first_date else None,
			"last_gift_date": getdate(last_date) if last_date else None,
			"last_gift_amount": last_gift_amount,
			"largest_gift_amount": flt(largest),
			"is_major_donor": _is_major_donor(donor, total),
		},
		update_modified=False,
	)


def _is_major_donor(donor: str, total_lifetime_amount: float) -> int:
	if frappe.db.get_value("Donor", donor, "donor_level") == "Major":
		return 1
	threshold = flt(frappe.db.get_single_value("Non Profit Settings", "major_donor_threshold"))
	return 1 if threshold and flt(total_lifetime_amount) >= threshold else 0


def recompute_major_gift_closed(major_gift: str) -> None:
	"""Set a Major Gift's closed amount from its submitted, paid Donations."""
	if not major_gift or not frappe.db.exists("Major Gift", major_gift):
		return
	donation = frappe.qb.DocType("Donation")
	total = (
		frappe.qb.from_(donation)
		.select(Sum(donation.amount))
		.where(donation.major_gift == major_gift)
		.where(donation.docstatus == 1)
		.where(donation.paid == 1)
	).run()[0][0]
	frappe.db.set_value("Major Gift", major_gift, "closed_amount", flt(total), update_modified=False)


def update_donor_last_interaction(donor: str, exclude: str | None = None) -> None:
	if not donor or not frappe.db.exists("Donor", donor):
		return
	interaction = frappe.qb.DocType("Donor Interaction")
	query = (
		frappe.qb.from_(interaction)
		.select(Max(interaction.interaction_date))
		.where(interaction.donor == donor)
	)
	if exclude:
		query = query.where(interaction.name != exclude)
	value = query.run()[0][0]
	frappe.db.set_value(
		"Donor",
		donor,
		"last_interaction_date",
		getdate(value) if value else None,
		update_modified=False,
	)


def update_major_gift_last_interaction(major_gift: str, exclude: str | None = None) -> None:
	if not major_gift or not frappe.db.exists("Major Gift", major_gift):
		return
	interaction = frappe.qb.DocType("Donor Interaction")
	query = (
		frappe.qb.from_(interaction)
		.select(Max(interaction.interaction_date))
		.where(interaction.major_gift == major_gift)
	)
	if exclude:
		query = query.where(interaction.name != exclude)
	value = query.run()[0][0]
	frappe.db.set_value(
		"Major Gift",
		major_gift,
		"last_interaction_date",
		getdate(value) if value else None,
		update_modified=False,
	)


def recompute_all_donor_giving() -> int:
	"""Recompute giving roll-ups for every Donor.

	Used by the install/migrate backfill patch and the daily reconciliation job.
	"""
	donors = frappe.get_all("Donor", pluck="name")
	for donor in donors:
		recompute_donor_giving(donor)
	return len(donors)


def recompute_all_major_gift_closed() -> int:
	"""Recompute the closed amount for every Major Gift."""
	gifts = frappe.get_all("Major Gift", pluck="name")
	for gift in gifts:
		recompute_major_gift_closed(gift)
	return len(gifts)


def reconcile_fundraising_rollups() -> None:
	"""Daily reconciliation job (registered in ``hooks.py`` ``scheduler_events``).

	Rebuilds every Donor giving roll-up and Major Gift closed amount so changes
	made outside the Donation doc-event hooks retro-apply: a ``Donation.paid``
	flag flipped through the Payment Entry flow (``db.set_value``, no hooks) and
	an edited ``Non Profit Settings.major_donor_threshold``.
	"""
	recompute_all_donor_giving()
	recompute_all_major_gift_closed()


# --- Workflow ------------------------------------------------------------

WORKFLOW_NAME = "Major Gift Pipeline"
WORKFLOW_STATE_STYLES = {
	"Identification": "Primary",
	"Qualification": "Info",
	"Cultivation": "Info",
	"Solicitation": "Warning",
	"Stewardship": "Warning",
	"Won": "Success",
	"Lost": "Danger",
}
# (from_state, action, to_state)
WORKFLOW_TRANSITIONS = (
	("Identification", "Qualify", "Qualification"),
	("Qualification", "Cultivate", "Cultivation"),
	("Cultivation", "Solicit", "Solicitation"),
	("Solicitation", "Move to Stewardship", "Stewardship"),
	("Cultivation", "Mark Won", "Won"),
	("Solicitation", "Mark Won", "Won"),
	("Stewardship", "Mark Won", "Won"),
	# Early disqualification: a gift can be marked Lost from any open stage,
	# including Identification / Qualification (no need to route through
	# Cultivation first).
	("Identification", "Mark Lost", "Lost"),
	("Qualification", "Mark Lost", "Lost"),
	("Cultivation", "Mark Lost", "Lost"),
	("Solicitation", "Mark Lost", "Lost"),
	("Stewardship", "Mark Lost", "Lost"),
	("Won", "Reopen", "Stewardship"),
	("Lost", "Reopen", "Qualification"),
)
# Preference order for the single role that may act on the workflow; the first
# one that exists on the site is used (Administrator can always transition).
WORKFLOW_ROLES = ("Non Profit Manager", "System Manager")

# Global-default key holding the hash of the shipped Workflow definition this
# site last built. The Workflow is rebuilt only when that hash changes, so
# operator edits (roles, extra transitions, ``is_active=0``) survive a migrate.
WORKFLOW_VERSION_KEY = "non_profit_major_gift_workflow_version"


def _workflow_definition_hash(edit_role: str) -> str:
	"""Stable hash of the shipped states / transitions / role, so a rebuild is
	triggered exactly when we change the definition (not on every migrate)."""
	import hashlib
	import json

	payload = json.dumps(
		{
			"states": list(WORKFLOW_STATE_STYLES.items()),
			"transitions": list(WORKFLOW_TRANSITIONS),
			"role": edit_role,
		},
		sort_keys=True,
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_major_gift_workflow() -> None:
	"""Create or version-refresh the Major Gift pipeline Workflow (idempotent).

	Uses the existing ``stage`` Select as the workflow state field, so pipeline
	stages double as workflow states and the form gets role-gated transition
	buttons. Allowed roles are filtered to those that exist on the site.

	The Workflow is (re)built only when it is missing or the shipped definition
	changed since this site last built it — an unconditional rebuild every
	migrate would revert operator edits (roles, transitions, ``is_active``).
	"""
	if not frappe.db.exists("DocType", "Major Gift"):
		return
	edit_role = next((role for role in WORKFLOW_ROLES if frappe.db.exists("Role", role)), None)
	if not edit_role:
		return

	definition_hash = _workflow_definition_hash(edit_role)
	if (
		frappe.db.exists("Workflow", WORKFLOW_NAME)
		and frappe.db.get_default(WORKFLOW_VERSION_KEY) == definition_hash
	):
		# Already built from the current shipped definition — leave it (and any
		# operator edits) untouched.
		return

	for state, style in WORKFLOW_STATE_STYLES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
			).insert(ignore_permissions=True)

	for _from_state, action, _to_state in WORKFLOW_TRANSITIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	workflow = (
		frappe.get_doc("Workflow", WORKFLOW_NAME)
		if frappe.db.exists("Workflow", WORKFLOW_NAME)
		else frappe.new_doc("Workflow")
	)
	workflow.workflow_name = WORKFLOW_NAME
	workflow.document_type = "Major Gift"
	workflow.workflow_state_field = "stage"
	workflow.is_active = 1
	workflow.send_email_alert = 0

	# One row per state / transition (not per role) so the stage list is not
	# duplicated. Transitions are gated to a single role; Administrator bypasses
	# role checks, so seeding/tests still walk the pipeline.
	workflow.set("states", [])
	for state in WORKFLOW_STATE_STYLES:
		workflow.append("states", {"state": state, "doc_status": "0", "allow_edit": edit_role})

	workflow.set("transitions", [])
	for from_state, action, to_state in WORKFLOW_TRANSITIONS:
		workflow.append(
			"transitions",
			{
				"state": from_state,
				"action": action,
				"next_state": to_state,
				"allowed": edit_role,
				"allow_self_approval": 1,
			},
		)

	workflow.flags.ignore_permissions = True
	workflow.save()
	frappe.db.set_default(WORKFLOW_VERSION_KEY, definition_hash)


# Programmatic stage advancement. The active Workflow blocks inserting a Major
# Gift directly into a non-initial stage and rejects any backward move, so
# seeders/tests create at the first stage and walk forward one legal transition
# at a time. The walk is derived from WORKFLOW_TRANSITIONS (single source of
# truth) and always starts at the gift's current stage, so advancing an
# already-progressed gift never emits a backward step.


def _forward_stage_path(from_stage: str, to_stage: str) -> list[str] | None:
	"""Shortest forward path of stages from ``from_stage`` to ``to_stage``.

	Walks the transition graph with the ``Reopen`` transitions removed, so a path
	never routes backward through a terminal stage. Returns the successive stages
	to move through (excluding ``from_stage``, ending at ``to_stage``), or
	``None`` when ``to_stage`` is not forward-reachable.
	"""
	if from_stage == to_stage:
		return []
	adjacency: dict[str, list[str]] = {}
	for source, action, dest in WORKFLOW_TRANSITIONS:
		if action == "Reopen":
			continue
		adjacency.setdefault(source, []).append(dest)

	queue: deque[list[str]] = deque([[from_stage]])
	seen = {from_stage}
	while queue:
		path = queue.popleft()
		for dest in adjacency.get(path[-1], []):
			if dest in seen:
				continue
			if dest == to_stage:
				return [*path[1:], dest]
			seen.add(dest)
			queue.append([*path, dest])
	return None


def advance_major_gift_to_stage(doc, target_stage: str):
	"""Move a Major Gift forward to ``target_stage``.

	With the pipeline Workflow active a stage is only reachable through
	single-step transitions and backward moves are rejected, so walk forward one
	valid transition at a time starting from the gift's *current* stage. Falls
	back to a direct set when no workflow is installed (or the target is not
	forward-reachable, e.g. a manual reopen). Runs as the current user
	(Administrator, during seeding/tests, has every role).
	"""
	from frappe.model.workflow import get_workflow_name

	if doc.stage == target_stage:
		return doc
	if not get_workflow_name(doc.doctype):
		doc.stage = target_stage
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		return doc

	path = _forward_stage_path(doc.stage, target_stage)
	if path is None:
		# Not forward-reachable (e.g. reopening a closed gift): let the workflow
		# validate the single direct transition.
		path = [target_stage]
	for state in path:
		doc.stage = state
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
	return doc
