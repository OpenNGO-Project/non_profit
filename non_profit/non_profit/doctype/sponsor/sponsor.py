import frappe
from frappe.model.document import Document


class Sponsor(Document):
	def validate(self):
		if self.contract_end and self.contract_start and self.contract_end < self.contract_start:
			frappe.throw("Contract End cannot be before Contract Start")
