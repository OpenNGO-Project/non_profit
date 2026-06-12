from datetime import date
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Count, Sum
from frappe.utils import cint, flt, getdate


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
		self.progress_percent = (self.total_raised / self.goal_amount * 100) if self.goal_amount else 0

	@frappe.whitelist()
	def refresh_totals(self) -> dict[str, float | int]:
		self._refresh_totals()
		self.save()
		return {
			"total_raised": self.total_raised,
			"donor_count": self.donor_count,
			"progress_percent": self.progress_percent,
		}


@frappe.whitelist()
def get_campaign_donation_chart(campaign: str, year: int | None = None) -> dict[str, Any]:
	if not campaign:
		frappe.throw(frappe._("Campaign is required."))

	campaign_doc = frappe.get_doc("Donation Campaign", campaign)
	campaign_doc.check_permission("read")

	today = getdate()
	selected_year = _selected_chart_year(year, today.year)
	year_start, year_end = _chart_year_bounds(selected_year, today)
	monthly_totals = [{"month": index + 1, "total": 0.0, "segments": []} for index in range(12)]
	donations = frappe.get_list(
		"Donation",
		filters={
			"docstatus": 1,
			"paid": 1,
			"campaign": campaign,
			"date": ["between", [year_start, year_end]],
		},
		fields=["name", "amount", "date", "donor", "donor_name"],
		order_by="date asc, modified asc",
		limit_page_length=0,
	)
	for donation in donations:
		donation_date = getdate(donation.get("date"))
		if donation_date.year != year_start.year:
			continue
		amount = flt(donation.get("amount"))
		month = monthly_totals[donation_date.month - 1]
		month["total"] += amount
		month["segments"].append(
			{
				"donation": donation.name,
				"label": donation.donor_name or donation.donor or donation.name,
				"total": amount,
			}
		)

	return {
		"campaign": campaign_doc.name,
		"title": campaign_doc.campaign_name or campaign_doc.name,
		"year": selected_year,
		"year_options": _chart_year_options(today.year),
		"currency": campaign_doc.currency or frappe.db.get_default("currency") or "EUR",
		"total": sum(month["total"] for month in monthly_totals),
		"donations_by_month": monthly_totals,
	}


def _selected_chart_year(year: int | None, current_year: int) -> int:
	allowed_years = _chart_year_options(current_year)
	selected_year = cint(year) if year else current_year
	if selected_year not in allowed_years:
		frappe.throw(frappe._("Please select a year from the last five years."))
	return selected_year


def _chart_year_options(current_year: int) -> list[int]:
	return [current_year - offset for offset in range(5)]


def _chart_year_bounds(year: int, today: date) -> tuple[date, date]:
	year_start = date(year, 1, 1)
	year_end = today if year == today.year else date(year, 12, 31)
	return year_start, year_end
