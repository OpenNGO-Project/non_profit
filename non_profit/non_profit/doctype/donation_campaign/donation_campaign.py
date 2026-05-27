import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Count, Sum
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
        donation = frappe.qb.DocType("Donation")
        total, donors = (
            frappe.qb.from_(donation)
            .select(Sum(donation.amount), Count(donation.donor).distinct())
            .where(donation.campaign == self.name)
            .where(donation.docstatus == 1)
            .where(donation.paid == 1)
        ).run()[0]
        self.total_raised = flt(total)
        self.donor_count = int(donors or 0)
        self.progress_percent = (
            (self.total_raised / self.goal_amount * 100) if self.goal_amount else 0
        )

    @frappe.whitelist()
    def refresh_totals(self) -> dict[str, float | int]:
        self._refresh_totals()
        self.save()
        return {
            "total_raised": self.total_raised,
            "donor_count": self.donor_count,
            "progress_percent": self.progress_percent,
        }
