# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from non_profit.non_profit.major_gifts import (
	update_donor_last_interaction,
	update_major_gift_last_interaction,
)


class DonorInteraction(Document):
	def validate(self):
		if not self.staff:
			self.staff = frappe.session.user
		if not self.interaction_date:
			self.interaction_date = now_datetime()

	def after_insert(self):
		self._sync_last_interaction()

	def on_update(self):
		self._sync_last_interaction()

	def on_trash(self):
		# on_trash runs before the row is removed, so drop this record from the
		# "latest interaction" recomputation explicitly.
		self._sync_last_interaction(exclude=self.name)

	def _sync_last_interaction(self, exclude: str | None = None):
		update_donor_last_interaction(self.donor, exclude=exclude)
		if self.major_gift:
			update_major_gift_last_interaction(self.major_gift, exclude=exclude)
