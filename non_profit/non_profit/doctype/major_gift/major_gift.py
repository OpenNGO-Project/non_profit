# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from non_profit.non_profit.major_gifts import TERMINAL_STAGES


class MajorGift(Document):
	def validate(self):
		self._validate_donor_change()
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"
		self._apply_stage_defaults()
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
			self.closed_on = None
			self.lost_reason = None

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
