# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.model.workflow import apply_workflow
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from non_profit.non_profit.major_gifts import TERMINAL_STAGES

OUTCOME_ACTIONS = {
	"Mark Won": ("Won", "won_reason"),
	"Mark Lost": ("Lost", "lost_reason"),
}


class MajorGift(Document):
	def validate(self):
		self._validate_donor_change()
		self._validate_follow_up_date()
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"
		self._apply_stage_defaults()
		self._validate_outcome_reason()
		self._refresh_closed_amount()

	def _validate_donor_change(self):
		if self.is_new() or not self.has_value_changed("donor"):
			return
		if frappe.db.exists("Donation", {"major_gift": self.name}) or frappe.db.exists(
			"Task", {"major_gift": self.name}
		):
			frappe.throw(frappe._("Donor cannot be changed after Donations or Tasks are linked."))

	def _apply_stage_defaults(self):
		if self.stage in TERMINAL_STAGES:
			if not self.closed_on:
				self.closed_on = getdate()
			if self.stage == "Won":
				self.lost_reason = None
			else:
				self.won_reason = None
		else:
			self.closed_on = None
			self.won_reason = None
			self.lost_reason = None

	def _validate_outcome_reason(self):
		fieldname = {"Won": "won_reason", "Lost": "lost_reason"}.get(self.stage)
		if not fieldname:
			return
		pending_outcome = frappe.flags.get("major_gift_outcome") or {}
		if (
			pending_outcome.get("name") == self.name
			and pending_outcome.get("stage") == self.stage
			and pending_outcome.get("fieldname") == fieldname
		):
			self.set(fieldname, pending_outcome.get("reason"))
		reason = (self.get(fieldname) or "").strip()
		self.set(fieldname, reason or None)
		if (
			not self.flags.ignore_permissions
			and (self.is_new() or self.has_value_changed("stage") or self.has_value_changed(fieldname))
			and not reason
		):
			frappe.throw(
				frappe._("{0} is required when marking a Major Gift as {1}.").format(
					self.meta.get_label(fieldname), self.stage
				)
			)

	def _validate_follow_up_date(self):
		if self.is_new() or not self.has_value_changed("next_action_date"):
			return
		before = self.get_doc_before_save()
		if before and before.next_action_task:
			frappe.throw(
				frappe._("Follow-up Date is controlled by the open Next Action Task {0}.").format(
					before.next_action_task
				)
			)

	def _refresh_closed_amount(self):
		if self.is_new():
			self.closed_amount = 0
			return
		donation = frappe.qb.DocType("Donation")
		total = (
			frappe.qb.from_(donation)
			.select(Sum(donation.amount))
			.where(donation.major_gift == self.name)
			.where(donation.docstatus == 1)
			.where(donation.paid == 1)
		).run()[0][0]
		self.closed_amount = flt(total)


@frappe.whitelist(methods=["POST"])
def apply_outcome_workflow(name: str, action: str, reason: str) -> dict:
	"""Apply a Won/Lost workflow action with its required reason atomically."""
	action = (action or "").strip()
	reason = (reason or "").strip()
	outcome = OUTCOME_ACTIONS.get(action)
	if not outcome:
		frappe.throw(frappe._("Unsupported Major Gift outcome action: {0}").format(action))
	if not reason:
		frappe.throw(frappe._("An outcome reason is required."))

	doc = frappe.get_doc("Major Gift", name)
	doc.check_permission("write")
	stage, fieldname = outcome
	previous_outcome = frappe.flags.get("major_gift_outcome")
	frappe.flags.major_gift_outcome = {
		"name": doc.name,
		"stage": stage,
		"fieldname": fieldname,
		"reason": reason,
	}
	try:
		return apply_workflow(doc.as_dict(), action).as_dict()
	finally:
		if previous_outcome is None:
			frappe.flags.pop("major_gift_outcome", None)
		else:
			frappe.flags.major_gift_outcome = previous_outcome
