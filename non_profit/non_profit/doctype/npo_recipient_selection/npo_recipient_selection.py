from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from non_profit.non_profit.recipient_selection import (
	count_canonical_candidates,
	evaluate_recipient_selection,
)


class NPORecipientSelection(Document):
	def validate(self) -> None:
		old = self.get_doc_before_save()
		if old and old.selection_name != self.selection_name:
			frappe.throw(_("Selection Name cannot be changed after the selection is created."))
		rows = evaluate_recipient_selection(self)
		self.candidate_count = count_canonical_candidates(rows)
		self.last_evaluated_on = now_datetime()
