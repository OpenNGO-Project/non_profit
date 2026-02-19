import frappe
from frappe.model.document import Document


class ChapterMemberRole(Document):
    def validate(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw(frappe._("End Date cannot be before Start Date"))
