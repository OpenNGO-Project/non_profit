from __future__ import annotations

import time
from collections import defaultdict
from hashlib import sha256
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, getdate, nowdate

from non_profit.non_profit.doctype.donor.donor import get_donor_email

DEFAULT_RECEIPT_COUNTRY = "Switzerland"
DONATION_RECEIPT_NAMING_SERIES = "NPO-DRCPT-DE-.YYYY.-"
YEARLY_RECEIPT_BATCH_SIZE = 200
YEARLY_RECEIPT_DEADLOCK_MAX_ATTEMPTS = 3
YEARLY_RECEIPT_JOB = (
	"non_profit.non_profit.doctype.donation_receipt.donation_receipt.process_yearly_receipt_batch"
)


class DonationReceipt(Document):
	def validate(self) -> None:
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
		context = self._get_donation_context()
		self._fill_donation_rows(context)
		self._set_accounting_identity(context)
		self._compute_total()
		if self.fiscal_year and not self.period_from:
			fiscal_year = frappe.get_doc("Fiscal Year", self.fiscal_year)
			self.period_from = fiscal_year.year_start_date
			self.period_to = fiscal_year.year_end_date

	def _get_donation_context(self) -> dict[str, Any]:
		donation_names = tuple(row.donation for row in self.donations or [] if row.donation)
		signature = (donation_names, self.name)
		cached = self.flags.get("donation_receipt_context")
		if cached and cached["signature"] == signature:
			return cached["context"]

		context = _load_donation_receipt_context(list(donation_names), current_receipt=self.name)
		self.flags.donation_receipt_context = {"signature": signature, "context": context}
		return context

	def _fill_donation_rows(self, context: dict[str, Any]) -> None:
		for row in self.donations or []:
			if not row.donation:
				continue
			donation = context["donations"].get(row.donation)
			if not donation:
				continue
			row.donation_date = donation.date
			row.amount = donation.amount

	def _set_accounting_identity(self, context: dict[str, Any], *, required: bool = False) -> None:
		companies = {
			donation.company for donation in context["donations"].values() if donation.get("company")
		}
		if len(companies) > 1:
			frappe.throw(_("All Donations on one receipt must belong to the same Company."))
		if companies:
			donation_company = next(iter(companies))
			if self.company and self.company != donation_company:
				frappe.throw(_("The receipt Company does not match its Donations."))
			self.company = donation_company
		elif not self.company:
			self.company = frappe.db.get_single_value("Non Profit Settings", "donation_company")

		company_currencies = context.get("company_currencies", {})
		company_currency = company_currencies.get(self.company)
		if self.company and self.company not in company_currencies:
			company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if self.currency and company_currency and self.currency != company_currency:
			frappe.throw(_("The receipt currency does not match the Donation Company currency."))
		if company_currency:
			self.currency = company_currency

		if required and not self.company:
			frappe.throw(_("A Company is required before submitting a Donation Receipt."))
		if required and not self.currency:
			frappe.throw(_("The Donation Receipt Company has no default currency."))

	def _compute_total(self) -> None:
		self.total_amount = sum(flt(row.amount) for row in self.donations or [])

	def before_submit(self) -> None:
		context = self._lock_donations_for_submit()
		self._fill_donation_rows(context)
		self._set_accounting_identity(context, required=True)
		self._compute_total()
		self._validate_donations_for_submit(context)
		self.status = "Issued"
		self.issued_on = nowdate()
		self.issued_by = frappe.session.user
		self._mark_donations()

	def _validate_donations_for_submit(self, context: dict[str, Any] | None = None) -> None:
		donation_names = [row.donation for row in self.donations or [] if row.donation]
		if not donation_names:
			frappe.throw(_("Add at least one Donation before submitting the receipt."))

		period_from = getdate(self.period_from) if self.period_from else None
		period_to = getdate(self.period_to) if self.period_to else None
		context = context or self._get_donation_context()
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
			if donation.company != self.company:
				frappe.throw(_("Donation {0} belongs to another Company.").format(frappe.bold(donation_name)))
			if context["company_currencies"].get(donation.company) != self.currency:
				frappe.throw(
					_("Donation {0} belongs to another currency group.").format(frappe.bold(donation_name))
				)
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

	def _lock_donations_for_submit(self) -> dict[str, Any]:
		"""Return complete current Donation and ownership state under row locks."""
		donation_names = sorted({row.donation for row in self.donations or [] if row.donation})
		context = _load_locked_donation_receipt_context(donation_names, current_receipt=self.name)
		signature = (tuple(row.donation for row in self.donations or [] if row.donation), self.name)
		self.flags.donation_receipt_context = {"signature": signature, "context": context}
		return context

	def _mark_donations(self) -> None:
		donation_names = list({row.donation for row in self.donations or [] if row.donation})
		if donation_names:
			frappe.db.set_value("Donation", {"name": ["in", donation_names]}, "receipt", self.name)

	def on_cancel(self) -> None:
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
		if self.docstatus != 1 or self.status != "Issued":
			frappe.throw(_("Only a submitted, issued Donation Receipt can be sent."))
		if self.country != DEFAULT_RECEIPT_COUNTRY:
			frappe.throw(_("Automated Donation Receipt sending is supported only for Switzerland."))
		if not self.email:
			frappe.throw(_("No donor email is stored on this receipt."))

		print_format = _approved_swiss_print_format()
		self._bind_delivery_addresses()
		frappe.sendmail(
			recipients=[self.email],
			subject=_("Donation Receipt {0}").format(self.fiscal_year),
			message=self._get_email_body(),
			attachments=[frappe.attach_print(self.doctype, self.name, print_format=print_format)],
		)
		self.db_set("email_sent_on", nowdate())
		return True

	def _bind_delivery_addresses(self) -> None:
		if not self.company:
			frappe.throw(_("The Donation Receipt has no Company."))
		if not self.currency:
			frappe.throw(_("The Donation Receipt has no deterministic currency."))

		company_address = _resolve_company_address(self.company, self.company_address)
		recipient_address = _resolve_recipient_address(self.donor, self.recipient_address)
		_validate_postal_address(company_address, _("Company issuer"), country=DEFAULT_RECEIPT_COUNTRY)
		_validate_postal_address(recipient_address, _("Donation Receipt recipient"))

		updates = {}
		if self.company_address != company_address:
			updates["company_address"] = company_address
		if self.recipient_address != recipient_address:
			updates["recipient_address"] = recipient_address
		if updates:
			self.db_set(updates, update_modified=False)

	def _get_email_body(self) -> str:
		return _(
			"<p>Dear {0},</p><p>Your donation receipt for {1} is attached.</p>"
			"<p>Thank you for your support.</p>"
		).format(self.donor_name, self.fiscal_year)


@frappe.whitelist(methods=["POST"])
def generate_yearly_receipts(
	fiscal_year: str,
	country: str | None = None,
	language: str = "de",
) -> dict[str, Any]:
	"""Queue bounded, permission-aware yearly receipt batches."""
	_require_receipt_generation_permissions()
	country = country or _default_receipt_country()
	_validate_receipt_reference("Country", country, _("Country"))
	_validate_receipt_reference("Language", language, _("Language"))
	fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
	fiscal_year_doc.check_permission("read")

	job_id = _enqueue_yearly_receipt_batch(
		fiscal_year=fiscal_year,
		period_from=str(fiscal_year_doc.year_start_date),
		period_to=str(fiscal_year_doc.year_end_date),
		country=country,
		language=language,
		requested_by=frappe.session.user,
		cursor=None,
	)
	return {"queued": True, "job_id": job_id, "created": 0, "receipts": []}


def process_yearly_receipt_batch(
	*,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	language: str,
	requested_by: str,
	cursor: str | None = None,
) -> dict[str, Any]:
	"""Process one bounded batch; transient lock conflicts replay the complete page."""
	if frappe.session.user != requested_by:
		frappe.throw(
			_("The yearly receipt job user no longer matches its requester."), frappe.PermissionError
		)
	_require_receipt_generation_permissions()
	result = _create_yearly_receipt_batch(
		fiscal_year=fiscal_year,
		period_from=period_from,
		period_to=period_to,
		country=country,
		language=language,
		cursor=cursor,
	)
	if result["next_cursor"]:
		_enqueue_yearly_receipt_batch(
			fiscal_year=fiscal_year,
			period_from=period_from,
			period_to=period_to,
			country=country,
			language=language,
			requested_by=requested_by,
			cursor=result["next_cursor"],
		)
	return result


def _enqueue_yearly_receipt_batch(
	*,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	language: str,
	requested_by: str,
	cursor: str | None,
) -> str:
	payload = "\n".join(
		(fiscal_year, period_from, period_to, country, language, requested_by, cursor or "START")
	)
	job_id = f"non-profit-yearly-receipts:{sha256(payload.encode()).hexdigest()}"
	frappe.enqueue(
		YEARLY_RECEIPT_JOB,
		queue="long",
		timeout=1200,
		enqueue_after_commit=True,
		deduplicate=True,
		job_id=job_id,
		fiscal_year=fiscal_year,
		period_from=period_from,
		period_to=period_to,
		country=country,
		language=language,
		requested_by=requested_by,
		cursor=cursor,
	)
	return job_id


def _create_yearly_receipt_batch(
	*,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	language: str,
	cursor: str | None = None,
) -> dict[str, Any]:
	"""Retry a complete atomic cursor page only after rolling back the failed transaction."""
	failed_attempts = 0
	while True:
		try:
			return _create_yearly_receipt_batch_once(
				fiscal_year=fiscal_year,
				period_from=period_from,
				period_to=period_to,
				country=country,
				language=language,
				cursor=cursor,
			)
		except frappe.QueryDeadlockError:
			failed_attempts += 1
			frappe.db.rollback()
			if failed_attempts >= YEARLY_RECEIPT_DEADLOCK_MAX_ATTEMPTS:
				raise
			time.sleep(0.25 * failed_attempts)


def _create_yearly_receipt_batch_once(
	*,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	language: str,
	cursor: str | None = None,
) -> dict[str, Any]:
	filters: dict[str, Any] = {
		"docstatus": 1,
		"paid": 1,
		"date": ["between", [period_from, period_to]],
		"donor": ["is", "set"],
	}
	if cursor:
		filters["name"] = [">", cursor]
	candidates = _yearly_receipt_candidates(filters)
	if not candidates:
		return {"created": 0, "receipts": [], "next_cursor": None}

	donation_names = [row.name for row in candidates]
	context = _load_locked_donation_receipt_context(donation_names)
	period_start = getdate(period_from)
	period_end = getdate(period_to)
	groups: dict[tuple[str, str, str, str, str, str], list[frappe._dict]] = defaultdict(list)
	for donation_name in donation_names:
		donation = context["donations"].get(donation_name)
		if not _eligible_for_yearly_receipt(
			donation,
			context["active_receipts"],
			period_start,
			period_end,
		):
			continue
		currency = context["company_currencies"].get(donation.company)
		if not currency:
			frappe.throw(
				_("Company {0} has no default currency for Donation {1}.").format(
					frappe.bold(donation.company), frappe.bold(donation.name)
				)
			)
		group_key = _yearly_receipt_group_key(
			donation,
			currency=currency,
			country=country,
			period_from=period_start,
			period_to=period_end,
		)
		groups[group_key].append(donation)

	created = []
	touched = []
	for group_key in sorted(groups):
		receipt_name, was_created = _create_or_extend_yearly_receipt_group(
			fiscal_year=fiscal_year,
			language=language,
			group_key=group_key,
			donations=groups[group_key],
			context=context,
		)
		if not receipt_name:
			continue
		touched.append(receipt_name)
		if was_created:
			created.append(receipt_name)

	next_cursor = donation_names[-1] if len(candidates) == YEARLY_RECEIPT_BATCH_SIZE else None
	return {"created": len(created), "receipts": touched, "next_cursor": next_cursor}


def _yearly_receipt_candidates(filters: dict[str, Any]) -> list[frappe._dict]:
	return frappe.get_list(
		"Donation",
		filters=filters,
		or_filters=[
			["Donation", "receipt", "is", "not set"],
			["Donation", "receipt", "=", ""],
		],
		fields=["name"],
		order_by="name asc",
		limit_page_length=YEARLY_RECEIPT_BATCH_SIZE,
	)


def _yearly_receipt_group_key(
	donation: frappe._dict,
	*,
	currency: str,
	country: str,
	period_from,
	period_to,
) -> tuple[str, str, str, str, str, str]:
	return (
		donation.company,
		currency,
		donation.donor,
		country,
		str(getdate(period_from)),
		str(getdate(period_to)),
	)


def _create_or_extend_yearly_receipt_group(
	*,
	fiscal_year: str,
	language: str,
	group_key: tuple[str, str, str, str, str, str],
	donations: list[frappe._dict],
	context: dict[str, Any],
) -> tuple[str | None, bool]:
	"""Create one exact group draft or append a later cursor page to it."""
	company, currency, donor, country, period_from, period_to = group_key
	if context["company_currencies"].get(company) != currency:
		frappe.throw(_("The Donation Company currency changed while yearly receipts were generated."))

	current_donations = []
	for candidate in donations:
		donation = context["donations"].get(candidate.name)
		if not _eligible_for_yearly_receipt(
			donation,
			context["active_receipts"],
			getdate(period_from),
			getdate(period_to),
		):
			continue
		current_key = _yearly_receipt_group_key(
			donation,
			currency=context["company_currencies"].get(donation.company),
			country=country,
			period_from=period_from,
			period_to=period_to,
		)
		if current_key != group_key:
			frappe.throw(
				_("Donation {0} changed receipt group while yearly receipts were generated.").format(
					frappe.bold(donation.name)
				)
			)
		current_donations.append(donation)
	if not current_donations:
		return None, False

	receipt = _locked_yearly_receipt_draft(
		fiscal_year=fiscal_year,
		language=language,
		group_key=group_key,
	)
	was_created = receipt is None
	if receipt is None:
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"naming_series": DONATION_RECEIPT_NAMING_SERIES,
				"donor": donor,
				"company": company,
				"currency": currency,
				"fiscal_year": fiscal_year,
				"period_from": period_from,
				"period_to": period_to,
				"country": country,
				"language": language,
			}
		)

	existing_donations = {row.donation for row in receipt.donations or [] if row.donation}
	new_donations = [donation for donation in current_donations if donation.name not in existing_donations]
	if not new_donations:
		return None, False
	for donation in new_donations:
		receipt.append(
			"donations",
			{
				"donation": donation.name,
				"donation_date": donation.date,
				"amount": donation.amount,
			},
		)

	# Existing rows were validated when reserved. Submit revalidates the complete
	# receipt; this save only needs the current, locked cursor page.
	receipt.flags.donation_receipt_context_for_validate = {
		"donations": {donation.name: donation for donation in new_donations},
		"active_receipts": {},
		"company_currencies": {company: currency},
	}
	if was_created:
		receipt.insert()
	else:
		receipt.save()
	return receipt.name, was_created


def _locked_yearly_receipt_draft(
	*,
	fiscal_year: str,
	language: str,
	group_key: tuple[str, str, str, str, str, str],
) -> DonationReceipt | None:
	company, currency, donor, country, period_from, period_to = group_key
	receipt = frappe.qb.DocType("Donation Receipt")
	rows = (
		frappe.qb.from_(receipt)
		.select(receipt.name)
		.where(receipt.docstatus == 0)
		.where(receipt.status == "Draft")
		.where(receipt.company == company)
		.where(receipt.currency == currency)
		.where(receipt.donor == donor)
		.where(receipt.fiscal_year == fiscal_year)
		.where(receipt.period_from == getdate(period_from))
		.where(receipt.period_to == getdate(period_to))
		.where(receipt.country == country)
		.where(receipt.language == language)
		.orderby(receipt.creation)
		.orderby(receipt.name)
		.limit(1)
		.for_update()
	).run()
	return frappe.get_doc("Donation Receipt", rows[0][0], for_update=True) if rows else None


def _eligible_for_yearly_receipt(
	donation: frappe._dict | None,
	active_receipts: dict[str, str],
	period_from,
	period_to,
) -> bool:
	if not donation or donation.docstatus != 1 or not donation.paid:
		return False
	if not donation.donor or not donation.company or donation.receipt:
		return False
	if donation.name in active_receipts or not donation.date:
		return False
	donation_date = getdate(donation.date)
	return period_from <= donation_date <= period_to


@frappe.whitelist()
def get_donations_for_selected_year(
	fiscal_year: str,
	donor: str,
	company: str | None = None,
) -> dict[str, Any]:
	if not fiscal_year:
		frappe.throw(_("Fiscal Year is required"))
	if not donor:
		frappe.throw(_("Donor is required"))
	if not frappe.has_permission("Donation Receipt", "create") and not frappe.has_permission(
		"Donation Receipt", "write"
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.has_permission("Donation", "read", throw=True)
	company = company or frappe.db.get_single_value("Non Profit Settings", "donation_company")
	if not company:
		frappe.throw(_("Select a receipt Company before loading Donations."))

	fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
	context = _load_donation_receipt_context(
		filters={
			"docstatus": 1,
			"paid": 1,
			"donor": donor,
			"company": company,
			"date": ["between", [fiscal_year_doc.year_start_date, fiscal_year_doc.year_end_date]],
		},
		or_filters=[
			["Donation", "receipt", "is", "not set"],
			["Donation", "receipt", "=", ""],
		],
		fields=["name", "date", "amount", "company"],
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
	return {
		"count": len(rows),
		"donations": rows,
		"company": company,
		"currency": context["company_currencies"].get(company),
	}


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
		return {"donations": {}, "active_receipts": {}, "company_currencies": {}}

	donation_filters = dict(filters or {})
	if donation_names:
		donation_filters["name"] = ["in", donation_names]
	donation_fields = list(
		dict.fromkeys(
			fields
			or ["name", "donor", "docstatus", "paid", "date", "amount", "receipt", "company", "creation"]
		)
	)
	for required_field in (
		"name",
		"donor",
		"docstatus",
		"paid",
		"date",
		"amount",
		"receipt",
		"company",
	):
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
	companies = {row.company for row in rows if row.company}
	return {
		"donations": donations,
		"active_receipts": _active_receipts_by_donation(list(donations), current_receipt),
		"company_currencies": _company_currencies(companies),
	}


def _load_locked_donation_receipt_context(
	donation_names: list[str],
	current_receipt: str | None = None,
) -> dict[str, Any]:
	donation_names = list(dict.fromkeys(name for name in donation_names if name))
	if not donation_names:
		return {"donations": {}, "active_receipts": {}, "company_currencies": {}}

	donation = frappe.qb.DocType("Donation")
	rows = (
		frappe.qb.from_(donation)
		.select(
			donation.name,
			donation.donor,
			donation.docstatus,
			donation.paid,
			donation.date,
			donation.amount,
			donation.receipt,
			donation.company,
			donation.creation,
		)
		.where(donation.name.isin(donation_names))
		.orderby(donation.name)
		.for_update()
	).run(as_dict=True)
	donations = {row.name: row for row in rows}
	companies = {row.company for row in rows if row.company}
	return {
		"donations": donations,
		"active_receipts": _active_receipts_by_donation(list(donations), current_receipt, for_update=True),
		"company_currencies": _company_currencies(companies, for_update=True),
	}


def _active_receipts_by_donation(
	donation_names: list[str],
	current_receipt: str | None = None,
	*,
	for_update: bool = False,
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
	if for_update:
		query = query.for_update()

	active_receipts: dict[str, str] = {}
	for row in query.run(as_dict=True):
		active_receipts.setdefault(row.donation, row.parent)
	return active_receipts


def _company_currencies(companies: set[str], *, for_update: bool = False) -> dict[str, str]:
	if not companies:
		return {}
	company = frappe.qb.DocType("Company")
	query = (
		frappe.qb.from_(company)
		.select(company.name, company.default_currency)
		.where(company.name.isin(sorted(companies)))
		.orderby(company.name)
	)
	if for_update:
		query = query.for_update()
	return {row.name: row.default_currency for row in query.run(as_dict=True)}


def _approved_swiss_print_format() -> str:
	print_format = frappe.db.get_single_value("Non Profit Settings", "swiss_donation_receipt_print_format")
	if not print_format:
		frappe.throw(
			_("Configure an operator-approved Swiss Donation Receipt Print Format in Non Profit Settings.")
		)
	if print_format == "Donation Receipt DE":
		frappe.throw(
			_("Donation Receipt DE contains German legal wording and is not approved for Switzerland.")
		)
	values = frappe.db.get_value("Print Format", print_format, ["doc_type", "disabled"], as_dict=True)
	if not values or values.doc_type != "Donation Receipt" or values.disabled:
		frappe.throw(
			_("The configured Swiss Donation Receipt Print Format is missing, disabled, or invalid.")
		)
	return print_format


def _resolve_company_address(company: str, selected_address: str | None = None) -> str:
	filters = [
		["Dynamic Link", "link_doctype", "=", "Company"],
		["Dynamic Link", "link_name", "=", company],
		["Address", "disabled", "=", 0],
	]
	addresses = frappe.get_all(
		"Address",
		filters=filters,
		fields=["name", "is_primary_address"],
		order_by="name asc",
		limit_page_length=0,
		distinct=True,
	)
	if selected_address:
		if selected_address not in {row.name for row in addresses}:
			frappe.throw(_("The stored Company issuer Address is no longer linked to the receipt Company."))
		return selected_address
	primary = [row.name for row in addresses if row.is_primary_address]
	if len(primary) == 1:
		return primary[0]
	if len(primary) > 1:
		frappe.throw(_("The receipt Company has more than one primary Address."))
	if len(addresses) == 1:
		return addresses[0].name
	if not addresses:
		frappe.throw(_("The receipt Company has no linked issuer Address."))
	frappe.throw(_("The receipt Company has multiple Addresses but no unique primary Address."))


def _resolve_recipient_address(donor: str, selected_address: str | None = None) -> str:
	from non_profit.non_profit.correspondence import get_correspondence_profile

	profile = get_correspondence_profile("Donor", donor)
	candidates = {row["name"] for row in profile.get("address_candidates") or []}
	if selected_address:
		if selected_address not in candidates:
			frappe.throw(_("The stored recipient Address no longer belongs to the receipt identity."))
		return selected_address
	if profile.get("address_name"):
		return profile["address_name"]
	frappe.throw(_("The Donation Receipt recipient has no unique postal Address."))


def _validate_postal_address(address_name: str, label: str, *, country: str | None = None) -> None:
	address = frappe.db.get_value(
		"Address",
		address_name,
		["address_line1", "pincode", "city", "country", "disabled"],
		as_dict=True,
	)
	if not address or address.disabled:
		frappe.throw(_("{0} Address is missing or disabled.").format(label))
	if not all(
		cstr(address.get(fieldname)).strip() for fieldname in ("address_line1", "pincode", "city", "country")
	):
		frappe.throw(_("{0} Address must include street, postal code, city, and country.").format(label))
	if country and address.country != country:
		frappe.throw(_("{0} Address must be in {1}.").format(label, country))


def _validate_receipt_reference(doctype: str, name: str, label: str) -> None:
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} is invalid.").format(label))


def _default_receipt_country() -> str:
	configured = frappe.db.get_single_value("Non Profit Settings", "default_receipt_country")
	if configured and frappe.db.exists("Country", configured):
		return configured
	if frappe.db.exists("Country", DEFAULT_RECEIPT_COUNTRY):
		return DEFAULT_RECEIPT_COUNTRY
	return frappe.db.get_default("country") or frappe.db.get_value("Country", {}, "name", order_by="name asc")


def _require_receipt_manager() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if roles.intersection({"System Manager", "Non Profit Manager"}):
		return
	frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_receipt_generation_permissions() -> None:
	_require_receipt_manager()
	frappe.has_permission("Donation Receipt", "create", throw=True)
	frappe.has_permission("Donation Receipt", "write", throw=True)
	frappe.has_permission("Donation", "read", throw=True)
