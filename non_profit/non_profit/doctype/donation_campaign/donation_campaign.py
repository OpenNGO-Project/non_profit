import frappe
from frappe.model.document import Document
from frappe.utils import flt


class DonationCampaign(Document):
	def validate(self):
		if self.end_date and self.start_date and self.end_date < self.start_date:
			frappe.throw("End Date cannot be before Start Date")
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"
		self._refresh_totals()

	def _refresh_totals(self):
		if self.is_new():
			self.total_raised = 0
			self.donor_count = 0
			self.progress_percent = 0
			return
		row = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(amount), 0) AS total, COUNT(DISTINCT donor) AS donors
			FROM `tabDonation`
			WHERE campaign = %s AND docstatus = 1 AND paid = 1
			""",
			self.name,
			as_dict=True,
		)[0]
		self.total_raised = flt(row.total)
		self.donor_count = int(row.donors or 0)
		self.progress_percent = (
			(self.total_raised / self.goal_amount * 100) if self.goal_amount else 0
		)

	@frappe.whitelist()
	def refresh_totals(self):
		self._refresh_totals()
		self.save()
		return {
			"total_raised": self.total_raised,
			"donor_count": self.donor_count,
			"progress_percent": self.progress_percent,
		}
