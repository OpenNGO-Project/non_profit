from __future__ import annotations

from collections.abc import Iterable, Mapping

import frappe

CHECK_PATH = "non_profit.non_profit.demo_data_reset.check_side_effects"
CLEANUP_PATH = "non_profit.non_profit.demo_data_reset.cleanup_side_effects"
DECLARED_DOCTYPES = (
	"Donation Tax Receipt",
	"Donation",
	"Major Gift",
	"Recurring Donation",
	"Sponsor",
	"Membership",
	"Member",
	"Donor",
	"Donation Campaign",
	"Volunteer",
)
CLEANUP_MANAGED_LINKS = (
	("Donor", "Donor", "next_action_task", "Task"),
	("Major Gift", "Major Gift", "next_action_task", "Task"),
)


def get_reset_declaration() -> dict[str, object]:
	"""Describe resettable records without depending on a reset consumer."""
	return {
		"doctypes": DECLARED_DOCTYPES,
		"side_effect_checks": (CHECK_PATH,),
		"side_effect_cleanup": CLEANUP_PATH,
		"cleanup_managed_links": CLEANUP_MANAGED_LINKS,
	}


def check_side_effects(
	*,
	reset_scope: Mapping[str, Iterable[str]],
	side_effect_scope: Mapping[str, Iterable[str]] | None,
) -> dict[str, list[str]]:
	"""Capture or verify installment evidence owned by captured schedules."""
	if not frappe.db.exists("DocType", "Recurring Donation Installment"):
		return {}
	if side_effect_scope is not None:
		return _existing_captured(side_effect_scope)

	schedules = tuple(reset_scope.get("Recurring Donation") or ())
	if not schedules:
		return {}
	installments = frappe.get_all(
		"Recurring Donation Installment",
		filters={"recurring_donation": ["in", schedules]},
		pluck="name",
		order_by="name asc",
		limit_page_length=0,
	)
	return {"Recurring Donation Installment": installments} if installments else {}


def cleanup_side_effects(
	*,
	reset_scope: Mapping[str, Iterable[str]],
	side_effect_scope: Mapping[str, Mapping[str, Iterable[str]]],
) -> None:
	next_action_links = _lock_and_validate_captured_next_action_links(reset_scope)
	names = tuple((side_effect_scope.get(CHECK_PATH) or {}).get("Recurring Donation Installment") or ())
	locked_installments = _lock_and_validate_captured_installments(reset_scope, names)

	for doctype, source_name in next_action_links:
		frappe.db.set_value(
			doctype,
			source_name,
			"next_action_task",
			None,
			update_modified=False,
		)
	if locked_installments:
		from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
			allow_reconciliation_write,
		)

		for name in locked_installments:
			installment = frappe.get_doc("Recurring Donation Installment", name)
			allow_reconciliation_write(installment)
			installment.delete(ignore_permissions=True)


def _lock_and_validate_captured_installments(
	reset_scope: Mapping[str, Iterable[str]], names: Iterable[str]
) -> list[str]:
	locked_installments = []
	schedules = set(reset_scope.get("Recurring Donation") or ())
	for name in names:
		row = frappe.db.get_value(
			"Recurring Donation Installment",
			name,
			["name", "recurring_donation"],
			as_dict=True,
			for_update=True,
		)
		if not row:
			continue
		if row.recurring_donation not in schedules:
			raise frappe.ValidationError(
				f"Captured Recurring Donation Installment {name} no longer belongs to the reset scope."
			)
		locked_installments.append(name)
	return locked_installments


def _lock_and_validate_captured_next_action_links(
	reset_scope: Mapping[str, Iterable[str]],
) -> list[tuple[str, str]]:
	task_names = tuple(reset_scope.get("Task") or ())
	if not task_names:
		return []
	links = []
	for doctype in ("Donor", "Major Gift"):
		source_names = tuple(reset_scope.get(doctype) or ())
		if not source_names:
			continue
		for source_name in source_names:
			row = frappe.db.get_value(
				doctype,
				source_name,
				["name", "next_action_task"],
				as_dict=True,
				for_update=True,
			)
			if not row or not row.next_action_task:
				continue
			if row.next_action_task not in task_names:
				raise frappe.ValidationError(
					f"Captured {doctype} {source_name} now links to out-of-scope Task {row.next_action_task}."
				)
			links.append((doctype, source_name))
	return links


def _existing_captured(side_effect_scope: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
	# Reset declarations stay import-free of their optional coordinator. This
	# deliberately small lookup mirrors the coordinator's provider contract.
	names = tuple(side_effect_scope.get("Recurring Donation Installment") or ())
	if not names:
		return {}
	remaining = frappe.get_all(
		"Recurring Donation Installment",
		filters={"name": ["in", names]},
		pluck="name",
		order_by="name asc",
		limit_page_length=0,
	)
	return {"Recurring Donation Installment": remaining} if remaining else {}
