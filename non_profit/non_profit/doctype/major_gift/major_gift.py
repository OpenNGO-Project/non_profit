# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from non_profit.non_profit.major_gifts import STAGE_PROBABILITY, TERMINAL_STAGES


class MajorGift(Document):
	def validate(self):
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"
		if flt(self.ask_amount) and not flt(self.expected_amount):
			self.expected_amount = self.ask_amount
		self._apply_stage_defaults()
		self.weighted_amount = flt(self.expected_amount) * flt(self.probability) / 100.0
		self._refresh_closed_amount()

	def _apply_stage_defaults(self):
		if self.stage in TERMINAL_STAGES:
			self.probability = 100 if self.stage == "Won" else 0
			self.outcome = self.stage
			if not self.closed_on:
				self.closed_on = getdate()
		else:
			self.outcome = None
			self.closed_on = None
			self.lost_reason = None
			# Seed a stage default only when the user has not set one yet.
			if not flt(self.probability):
				self.probability = STAGE_PROBABILITY.get(self.stage, 0)

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
