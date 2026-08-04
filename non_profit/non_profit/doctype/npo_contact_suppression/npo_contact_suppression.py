from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr


class NPOContactSuppression(Document):
	def validate(self) -> None:
		identity_kind = cstr(frappe.db.get_value("Contact", self.contact, "npo_identity_kind")).strip()
		if identity_kind == "Generic Endpoint":
			frappe.throw(
				_("A Generic Endpoint Contact is not a person and cannot carry a contact suppression.")
			)
