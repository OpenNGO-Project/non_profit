from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from non_profit.non_profit.doctype.donor.donor import get_donor_email

DEFAULT_RECEIPT_COUNTRY = "Switzerland"


class DonationReceipt(Document):
	def validate(self):
		if self.donor:
			self.email = get_donor_email(self.donor) or self.email
		preloaded_context = self.flags.pop("donation_receipt_context_for_validate", None)
		self.flags.pop("donation_receipt_context", None)
		if preloaded_context:
			donation_names = tuple(row.donation for row in self.donations or [] if row.donation)
			self.flags.donation_receipt_context = {
				"signature": (donation_names, self.name),
				"context": preloaded_context,
			}
		self._fill_donation_rows(self._get_donation_context())
		self._compute_total()
		if self.fiscal_year and not self.period_from:
			fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
			self.period_from = fy.year_start_date
			self.period_to = fy.year_end_date

	def _get_donation_context(self) -> dict[str, Any]:
		donation_names = tuple(row.donation for row in self.donations or [] if row.donation)
		signature = (donation_names, self.name)
		cached = self.flags.get("donation_receipt_context")
		if cached and cached["signature"] == signature:
			return cached["context"]

		context = _load_donation_receipt_context(list(donation_names), current_receipt=self.name)
		self.flags.donation_receipt_context = {"signature": signature, "context": context}
		return context

	def _fill_donation_rows(self, context: dict[str, Any]):
		for row in self.donations or []:
			if not row.donation:
				continue
			donation = context["donations"].get(row.donation)
			if not donation:
				continue
			row.donation_date = donation.date
			row.amount = donation.amount

	def _compute_total(self):
		total = 0
		for row in self.donations or []:
			total += flt(row.amount)
		self.total_amount = total
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"

	def before_submit(self):
		self._lock_donations_for_submit()
		self._validate_donations_for_submit()
		self.status = "Issued"
		self.issued_on = nowdate()
		self.issued_by = frappe.session.user
		self._mark_donations()

	def _validate_donations_for_submit(self):
		donation_names = [row.donation for row in self.donations or [] if row.donation]
		if not donation_names:
			frappe.throw(_("Add at least one Donation before submitting the receipt."))

		period_from = getdate(self.period_from) if self.period_from else None
		period_to = getdate(self.period_to) if self.period_to else None
		context = self._get_donation_context()
		seen = set()
		for donation_name in donation_names:
			if donation_name in seen:
				frappe.throw(_("Donation {0} is listed more than once.").format(frappe.bold(donation_name)))
			seen.add(donation_name)
			donation = context["donations"].get(donation_name)
			if not donation:
				frappe.throw(_("Donation {0} does not exist.").format(frappe.bold(donation_name)))
			if donation.donor != self.donor:
				frappe.throw(_("Donation {0} belongs to another donor.").format(frappe.bold(donation_name)))
			if donation.docstatus != 1:
				frappe.throw(_("Donation {0} must be submitted.").format(frappe.bold(donation_name)))
			if not donation.paid:
				frappe.throw(_("Donation {0} must be paid.").format(frappe.bold(donation_name)))
			donation_date = getdate(donation.date) if donation.date else None
			if period_from and donation_date and donation_date < period_from:
				frappe.throw(
					_("Donation {0} is outside the receipt period.").format(frappe.bold(donation_name))
				)
			if period_to and donation_date and donation_date > period_to:
				frappe.throw(
					_("Donation {0} is outside the receipt period.").format(frappe.bold(donation_name))
				)
			if donation.receipt and donation.receipt != self.name:
				frappe.throw(_("Donation {0} already has a receipt.").format(frappe.bold(donation_name)))
			other_receipt = context["active_receipts"].get(donation_name)
			if other_receipt:
				frappe.throw(
					_("Donation {0} is already linked to receipt {1}.").format(
						frappe.bold(donation_name), frappe.bold(other_receipt)
					)
				)

	def _lock_donations_for_submit(self) -> None:
		"""Serialize receipt ownership checks for every selected Donation."""
		donation_names = sorted({row.donation for row in self.donations or [] if row.donation})
		if not donation_names:
			return
		donation = frappe.qb.DocType("Donation")
		(
			frappe.qb.from_(donation)
			.select(donation.name)
			.where(donation.name.isin(donation_names))
			.orderby(donation.name)
			.for_update()
		).run()
		# validate() may have cached ownership before this transaction acquired
		# the locks. Re-read Donation.receipt and active receipt items now.
		self.flags.pop("donation_receipt_context", None)

	def _mark_donations(self):
		donation_names = list({row.donation for row in self.donations or [] if row.donation})
		if donation_names:
			frappe.db.set_value("Donation", {"name": ["in", donation_names]}, "receipt", self.name)

	def on_cancel(self):
		self.status = "Cancelled"
		donation_names = list({row.donation for row in self.donations or [] if row.donation})
		if donation_names:
			frappe.db.set_value(
				"Donation",
				{"name": ["in", donation_names], "receipt": self.name},
				"receipt",
				None,
			)

	@frappe.whitelist()
	def send_to_donor(self) -> bool:
		self.check_permission("write")
		if not self.email:
			frappe.throw(_("No donor email"))
		frappe.sendmail(
			recipients=[self.email],
			subject=f"Zuwendungsbestätigung {self.fiscal_year}",
			message=self._get_email_body(),
			attachments=[frappe.attach_print(self.doctype, self.name, print_format="Donation Receipt DE")],
		)
		self.db_set("email_sent_on", nowdate())
		return True

	def _get_email_body(self):
		return f"""<p>Liebe/r {self.donor_name},</p>
<p>im Anhang erhalten Sie Ihre Zuwendungsbestätigung für das Jahr {self.fiscal_year}.</p>
<p>Herzlichen Dank für Ihre Unterstützung!</p>"""


@frappe.whitelist()
def generate_yearly_receipts(
	fiscal_year: str,
	country: str | None = None,
	language: str = "de",
) -> dict[str, Any]:
	_require_receipt_manager()
	country = country or _default_receipt_country()
	fy = frappe.get_doc("Fiscal Year", fiscal_year)
	start, end = fy.year_start_date, fy.year_end_date
	context = _load_donation_receipt_context(
		filters={
			"docstatus": 1,
			"paid": 1,
			"date": ["between", [start, end]],
			"donor": ["is", "set"],
		},
		or_filters=[
			["Donation", "receipt", "is", "not set"],
			["Donation", "receipt", "=", ""],
		],
		order_by="donor asc, date asc, creation asc",
	)
	donations_by_donor: dict[str, list[frappe._dict]] = {}
	for donation in context["donations"].values():
		if donation.name not in context["active_receipts"]:
			donations_by_donor.setdefault(donation.donor, []).append(donation)

	created = []
	for donor, donations in donations_by_donor.items():
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor,
				"fiscal_year": fiscal_year,
				"period_from": start,
				"period_to": end,
				"country": country,
				"language": language,
				"donations": [
					{
						"donation": donation.name,
						"donation_date": donation.date,
						"amount": donation.amount,
					}
					for donation in donations
				],
			}
		)
		receipt.flags.ignore_permissions = True
		receipt.flags.donation_receipt_context_for_validate = {
			"donations": {donation.name: donation for donation in donations},
			"active_receipts": {},
		}
		receipt.insert()
		created.append(receipt.name)
	return {"created": len(created), "receipts": created}


@frappe.whitelist()
def get_donations_for_selected_year(fiscal_year: str, donor: str) -> dict[str, Any]:
	if not fiscal_year:
		frappe.throw(_("Fiscal Year is required"))
	if not donor:
		frappe.throw(_("Donor is required"))
	if not frappe.has_permission("Donation Receipt", "create") and not frappe.has_permission(
		"Donation Receipt", "write"
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.has_permission("Donation", "read", throw=True)

	fy = frappe.get_doc("Fiscal Year", fiscal_year)
	context = _load_donation_receipt_context(
		filters={
			"docstatus": 1,
			"paid": 1,
			"donor": donor,
			"date": ["between", [fy.year_start_date, fy.year_end_date]],
		},
		or_filters=[
			["Donation", "receipt", "is", "not set"],
			["Donation", "receipt", "=", ""],
		],
		fields=["name", "date", "amount"],
		order_by="date asc, creation asc",
		permission_aware=True,
	)
	rows = [
		{
			"donation": donation.name,
			"donation_date": donation.date,
			"amount": donation.amount,
		}
		for donation in context["donations"].values()
		if donation.name not in context["active_receipts"]
	]
	return {"count": len(rows), "donations": rows}


def _active_receipt_for_donation(donation_name: str, current_receipt: str | None = None) -> str | None:
	return _active_receipts_by_donation([donation_name], current_receipt).get(donation_name)


def _donations_linked_to_active_receipts(donation_names: list[str]) -> set[str]:
	return set(_active_receipts_by_donation(donation_names))


def _donation_receipt_row(donation_name: str) -> dict[str, Any]:
	donation = _load_donation_receipt_context([donation_name])["donations"].get(donation_name) or {}
	return {
		"donation": donation_name,
		"donation_date": donation.get("date"),
		"amount": donation.get("amount"),
	}


def _load_donation_receipt_context(
	donation_names: list[str] | None = None,
	*,
	filters: dict[str, Any] | None = None,
	or_filters: list[list[Any]] | None = None,
	fields: list[str] | None = None,
	order_by: str | None = None,
	current_receipt: str | None = None,
	permission_aware: bool = False,
) -> dict[str, Any]:
	donation_names = list(dict.fromkeys(name for name in donation_names or [] if name))
	if donation_names == [] and filters is None:
		return {"donations": {}, "active_receipts": {}}

	donation_filters = dict(filters or {})
	if donation_names:
		donation_filters["name"] = ["in", donation_names]
	donation_fields = list(
		dict.fromkeys(
			fields or ["name", "donor", "docstatus", "paid", "date", "amount", "receipt", "creation"]
		)
	)
	for required_field in ("name", "donor", "docstatus", "paid", "date", "amount", "receipt"):
		if required_field not in donation_fields:
			donation_fields.append(required_field)

	get_rows = frappe.get_list if permission_aware else frappe.get_all
	rows = get_rows(
		"Donation",
		filters=donation_filters,
		or_filters=or_filters,
		fields=donation_fields,
		order_by=order_by,
		limit_page_length=0,
	)
	donations = {row.name: row for row in rows}
	return {
		"donations": donations,
		"active_receipts": _active_receipts_by_donation(list(donations), current_receipt),
	}


def _active_receipts_by_donation(
	donation_names: list[str], current_receipt: str | None = None
) -> dict[str, str]:
	donation_names = list(dict.fromkeys(name for name in donation_names if name))
	if not donation_names:
		return {}

	item = frappe.qb.DocType("Donation Receipt Item")
	receipt = frappe.qb.DocType("Donation Receipt")
	query = (
		frappe.qb.from_(item)
		.inner_join(receipt)
		.on(receipt.name == item.parent)
		.select(item.donation, item.parent)
		.where(item.parenttype == "Donation Receipt")
		.where(item.donation.isin(donation_names))
		.where(receipt.docstatus < 2)
		.orderby(item.parent)
	)
	if current_receipt:
		query = query.where(item.parent != current_receipt)

	active_receipts: dict[str, str] = {}
	for row in query.run(as_dict=True):
		active_receipts.setdefault(row.donation, row.parent)
	return active_receipts


def _default_receipt_country() -> str:
	if frappe.db.exists("Country", DEFAULT_RECEIPT_COUNTRY):
		return DEFAULT_RECEIPT_COUNTRY
	return frappe.db.get_default("country") or frappe.db.get_value("Country", {}, "name", order_by="name asc")


def _require_receipt_manager() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if roles.intersection({"System Manager", "Non Profit Manager"}):
		return
	frappe.throw(_("Not permitted"), frappe.PermissionError)
