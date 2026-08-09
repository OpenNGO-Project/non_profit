from pathlib import Path
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests import UnitTestCase

from non_profit import hooks as app_hooks
from non_profit.non_profit.demo_data_reset import (
	CHECK_PATH,
	CLEANUP_MANAGED_LINKS,
	CLEANUP_PATH,
	DECLARED_DOCTYPES,
	check_side_effects,
	cleanup_side_effects,
	get_reset_declaration,
)


class TestDemoDataResetDeclaration(UnitTestCase):
	def test_provider_is_neutral_and_declares_complete_owned_scope(self) -> None:
		declaration = get_reset_declaration()

		self.assertEqual(
			DECLARED_DOCTYPES,
			(
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
			),
		)
		self.assertEqual(
			CLEANUP_MANAGED_LINKS,
			(
				("Donor", "Donor", "next_action_task", "Task"),
				("Major Gift", "Major Gift", "next_action_task", "Task"),
			),
		)
		self.assertEqual(
			declaration,
			{
				"doctypes": DECLARED_DOCTYPES,
				"side_effect_checks": (CHECK_PATH,),
				"side_effect_cleanup": CLEANUP_PATH,
				"cleanup_managed_links": CLEANUP_MANAGED_LINKS,
			},
		)
		self.assertEqual(
			app_hooks.demo_data_reset_declarations,
			["non_profit.non_profit.demo_data_reset.get_reset_declaration"],
		)
		source = Path(__file__).with_name("demo_data_reset.py").read_text(encoding="utf-8")
		self.assertNotIn("import good_", source)
		self.assertNotIn("from good_", source)

	def test_verification_queries_only_captured_installment_names(self) -> None:
		with (
			patch("non_profit.non_profit.demo_data_reset.frappe.db.exists", return_value=True),
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.get_all",
				return_value=["RDI-EPOCH"],
			) as get_all,
		):
			result = check_side_effects(
				reset_scope={"Recurring Donation": ("RD-OTHER",)},
				side_effect_scope={"Recurring Donation Installment": ("RDI-EPOCH",)},
			)

		get_all.assert_called_once_with(
			"Recurring Donation Installment",
			filters={"name": ["in", ("RDI-EPOCH",)]},
			pluck="name",
			order_by="name asc",
			limit_page_length=0,
		)
		self.assertEqual(result, {"Recurring Donation Installment": ["RDI-EPOCH"]})

	def test_cleanup_deletes_only_captured_installments_through_owner_guard(self) -> None:
		installment = Mock()
		with (
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.db.get_value",
				return_value=frappe._dict(name="RDI-EPOCH", recurring_donation="RD-OTHER"),
			),
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.get_doc", return_value=installment
			) as get_doc,
			patch(
				"non_profit.non_profit.doctype.recurring_donation_installment."
				"recurring_donation_installment.allow_reconciliation_write"
			) as allow_write,
		):
			cleanup_side_effects(
				reset_scope={"Recurring Donation": ("RD-OTHER",)},
				side_effect_scope={
					CHECK_PATH: {"Recurring Donation Installment": ("RDI-EPOCH",)},
					"other.check": {"Recurring Donation Installment": ("RDI-OTHER",)},
				},
			)

		get_doc.assert_called_once_with("Recurring Donation Installment", "RDI-EPOCH")
		allow_write.assert_called_once_with(installment)
		installment.delete.assert_called_once_with(ignore_permissions=True)

	def test_cleanup_clears_only_captured_reciprocal_task_links(self) -> None:
		def current_link(doctype, name, fields, *, as_dict, for_update):
			return frappe._dict(name=name, next_action_task="TASK-EPOCH")

		with (
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.db.get_value",
				side_effect=current_link,
			),
			patch("non_profit.non_profit.demo_data_reset.frappe.db.set_value") as set_value,
		):
			cleanup_side_effects(
				reset_scope={
					"Donor": ("DONOR-EPOCH",),
					"Major Gift": ("MAJOR GIFT-EPOCH",),
					"Task": ("TASK-EPOCH",),
				},
				side_effect_scope={CHECK_PATH: {}},
			)

		self.assertEqual(
			set_value.call_args_list,
			[
				call(
					"Donor",
					"DONOR-EPOCH",
					"next_action_task",
					None,
					update_modified=False,
				),
				call(
					"Major Gift",
					"MAJOR GIFT-EPOCH",
					"next_action_task",
					None,
					update_modified=False,
				),
			],
		)

	def test_cleanup_rejects_reassigned_reciprocal_task_link(self) -> None:
		with (
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.db.get_value",
				return_value=frappe._dict(name="DONOR-EPOCH", next_action_task="TASK-REAL"),
			),
			patch("non_profit.non_profit.demo_data_reset.frappe.db.set_value") as set_value,
			self.assertRaises(frappe.ValidationError),
		):
			cleanup_side_effects(
				reset_scope={"Donor": ("DONOR-EPOCH",), "Task": ("TASK-EPOCH",)},
				side_effect_scope={CHECK_PATH: {}},
			)

		set_value.assert_not_called()

	def test_cleanup_validates_installments_before_clearing_reciprocal_links(self) -> None:
		def current_owner(doctype, name, fields, *, as_dict, for_update):
			if doctype == "Recurring Donation Installment":
				return frappe._dict(name=name, recurring_donation="RD-REAL")
			return frappe._dict(name=name, next_action_task="TASK-EPOCH")

		with (
			patch(
				"non_profit.non_profit.demo_data_reset.frappe.db.get_value",
				side_effect=current_owner,
			),
			patch("non_profit.non_profit.demo_data_reset.frappe.db.set_value") as set_value,
			self.assertRaises(frappe.ValidationError),
		):
			cleanup_side_effects(
				reset_scope={
					"Donor": ("DONOR-EPOCH",),
					"Task": ("TASK-EPOCH",),
					"Recurring Donation": ("RD-EPOCH",),
				},
				side_effect_scope={CHECK_PATH: {"Recurring Donation Installment": ("RDI-EPOCH",)}},
			)

		set_value.assert_not_called()
