"""Spendenbescheinigungen — annual donation tax receipts.

non_profit owns the *business* data: which donations qualify, how they are
aggregated per donor and tax year, and the receipt lifecycle
(`Donation Tax Receipt`). Production and postal dispatch of the actual letters
belong to an optional downstream campaign app, which this module feeds through
an audience-provider contract.

The seam is deliberately one-directional and late-bound: nothing here imports
the campaign app at module level, so non_profit stays independently installable.
`create_receipt_campaign` resolves its helper with `frappe.get_attr` and fails
with a clear message when the integration is absent.

Operator procedure (see HOW_TO.md): generate → review the Drafts →
`create_receipt_campaign` → prepare/freeze/generate/post in direct mail →
`mark_receipts_issued`.

Open business questions recorded in
`LETTER_DISPATCH_CONVERGENCE_PLAN_2026-07-31.md` and deliberately NOT decided
here: further qualifying-donation refinements (minimum amounts, in-kind gifts,
membership fees), cantonal receipt format variations, and the signature image.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, escape_html, flt, fmt_money, formatdate, getdate, now_datetime, nowdate

from non_profit.non_profit.doctype.donation_tax_receipt.donation_tax_receipt import (
	DEFAULT_RECEIPT_CURRENCY,
	MAX_TAX_YEAR,
	MIN_TAX_YEAR,
	_authorize_receipt_service_write,
	receipt_currency,
)
from non_profit.non_profit.doctype.donor.donor import get_donor_email
from non_profit.non_profit.fundraising_setup import receipt_print_format_for
from non_profit.non_profit.mailer import send_queued_email_now, send_referenced_email
from non_profit.non_profit.recipient_selection import _donor_canonical_subject

RECEIPT_DOCTYPE = "Donation Tax Receipt"
CAMPAIGN_DOCTYPE = "Good Direct Mail Campaign"
AUDIENCE_PROVIDER_KEY = "donation_tax_receipt"
CREATE_PRODUCER_CAMPAIGN = "good_direct_mail.services.producers.create_producer_campaign"
DEFAULT_PRINT_FORMAT = "Good Direct Mail Letter"
DEFAULT_LETTER_TITLE = "Spendenbescheinigung {0}"
DEFAULT_LETTER_BODY = """<p>{{ salutation }}</p>
<p>Herzlichen Dank für Ihre Unterstützung im Jahr {{ tax_year }}.</p>
<p>Sie haben uns im Jahr {{ tax_year }} insgesamt {{ receipt_total }} gespendet
({{ donation_count }} Zuwendungen):</p>
{{ donation_table_html }}
<p>Diese Bescheinigung dient als Nachweis für Ihre Steuererklärung.</p>"""
# The optional postal integration owns "Direct Mail Manager". The role name is
# a cross-app string contract because this app must not import the integration.
DISPATCH_ROLES = ("System Manager", "Direct Mail Manager")


def receipt_campaign_reference(company: str, tax_year: int) -> str:
	"""Build the opaque provider reference `<company>|<tax_year>`."""
	return f"{company}|{cint(tax_year)}"


def direct_mail_audience_provider() -> dict[str, str]:
	"""Describe the tax-receipt audience to a postal campaign consumer."""
	return {
		"key": AUDIENCE_PROVIDER_KEY,
		"label": _("Donation Tax Receipts"),
		"get_rows": "non_profit.non_profit.tax_receipts.direct_mail_candidate_rows",
	}


@frappe.whitelist(methods=["POST"])
def generate_receipts(company: str, tax_year: int) -> dict[str, Any]:
	"""Create or refresh Draft receipts for one Company and calendar tax year.

	Qualifying donations are submitted (`docstatus 1`), paid, belong to the Company,
	are dated inside the calendar year, carry a positive amount, and name a
	Donor. Re-running is idempotent: an unchanged Draft is left alone and an
	already Issued receipt is never rewritten silently — it is reported under
	`stale_issued` for manual amendment instead.
	"""
	frappe.has_permission("Donation", "read", throw=True)
	for permission_type in ("create", "write", "delete"):
		frappe.has_permission(RECEIPT_DOCTYPE, permission_type, throw=True)
	company = _validated_company(company)
	tax_year = _validated_tax_year(tax_year)
	_lock_generation_scope(company)

	donations_by_donor = _qualifying_donations(company, tax_year)
	existing = {row.donor: row for row in _locked_existing_receipts(company, tax_year)}

	report: dict[str, Any] = {
		"created": 0,
		"updated": 0,
		"deleted": 0,
		"unchanged": 0,
		"stale_issued": [],
	}
	for donor in sorted(set(donations_by_donor) | set(existing)):
		_reconcile_donor_receipt(
			company=company,
			tax_year=tax_year,
			donor=donor,
			details=donations_by_donor.get(donor),
			record=existing.get(donor),
			report=report,
		)
	report["stale_issued"].sort()
	return report


def _reconcile_donor_receipt(
	*,
	company: str,
	tax_year: int,
	donor: str,
	details: list[dict[str, Any]] | None,
	record: Any,
	report: dict[str, Any],
) -> None:
	"""Bring one donor's receipt in line with that donor's donations.

	Extracted so the whole-year batch and the single-donor action below cannot
	drift apart: which receipts may be rewritten, which are protected once
	Issued, and which stay dead once Cancelled is one decision, made here.
	"""
	if not details:
		if record.status == "Draft":
			_delete_draft_receipt(record.name)
			report["deleted"] += 1
		elif record.status == "Issued":
			report["stale_issued"].append(record.name)
		return
	total = flt(sum(row["amount"] for row in details))
	if record is None:
		_insert_draft_receipt(company, tax_year, donor, details, total)
		report["created"] += 1
		return
	if _receipt_matches(record, details, total):
		report["unchanged"] += 1
		return
	if record.status == "Issued":
		report["stale_issued"].append(record.name)
		return
	if record.status == "Cancelled":
		# A cancelled receipt is an operator decision; never revive it.
		report["unchanged"] += 1
		return
	_update_draft_receipt(record.name, details, total)
	report["updated"] += 1


@frappe.whitelist()
def generate_receipt_for_donor(donor: str, company: str, tax_year: int) -> dict[str, Any]:
	"""Create or refresh the Draft receipt of a single donor.

	The annual batch is the normal route; this is the counter case — a donor
	rings up in March asking for last year's Bescheinigung, and the
	Geschäftsstelle should not have to re-run the whole year to answer.

	Same permissions, same locking and the same reconciliation rules as
	`generate_receipts`, so a receipt produced here is indistinguishable from
	one the batch would have produced. The report has the batch's shape too,
	counting exactly one donor.
	"""
	frappe.has_permission("Donation", "read", throw=True)
	for permission_type in ("create", "write", "delete"):
		frappe.has_permission(RECEIPT_DOCTYPE, permission_type, throw=True)
	if not frappe.db.exists("Donor", donor):
		frappe.throw(_("Donor {0} does not exist.").format(frappe.bold(donor)))
	company = _validated_company(company)
	tax_year = _validated_tax_year(tax_year)
	_lock_generation_scope(company)

	details = _qualifying_donations(company, tax_year).get(donor)
	record = next(
		(row for row in _locked_existing_receipts(company, tax_year) if row.donor == donor),
		None,
	)
	if not details and record is None:
		frappe.throw(
			_("{0} has no paid, submitted donations for {1} in {2}.").format(
				frappe.bold(frappe.db.get_value("Donor", donor, "donor_name") or donor),
				frappe.bold(tax_year),
				frappe.bold(company),
			)
		)

	report: dict[str, Any] = {
		"created": 0,
		"updated": 0,
		"deleted": 0,
		"unchanged": 0,
		"stale_issued": [],
	}
	_reconcile_donor_receipt(
		company=company,
		tax_year=tax_year,
		donor=donor,
		details=details,
		record=record,
		report=report,
	)
	report["receipt"] = frappe.db.get_value(
		RECEIPT_DOCTYPE, {"company": company, "tax_year": tax_year, "donor": donor}, "name"
	)
	return report


def direct_mail_candidate_rows(reference: str) -> list[dict[str, Any]]:
	"""Postal audience provider: one letter row per receipt.

	`reference` is `<company>|<tax_year>`. Donors whose canonical postal
	subject cannot be resolved (no Contact, Customer, or Household) are skipped
	and logged; postal output can only address a canonical subject.
	"""
	company, tax_year = _parse_reference(reference)
	receipts = frappe.get_all(
		RECEIPT_DOCTYPE,
		filters={
			"company": company,
			"tax_year": tax_year,
			"status": "Draft",
		},
		fields=["name", "donor", "donor_name", "total_amount", "donation_count", "donation_details"],
		order_by="donor asc, name asc",
		limit=0,
	)
	if not receipts:
		return []

	donors = {
		row.name: row
		for row in frappe.get_all(
			"Donor",
			filters={"name": ["in", sorted({receipt.donor for receipt in receipts})]},
			fields=[
				"name",
				"donor_name",
				"subject_type",
				"contact",
				"customer",
				"subject_household",
				"preferred_language",
			],
			limit=0,
		)
	}

	rows: list[dict[str, Any]] = []
	skipped: list[str] = []
	for receipt in receipts:
		donor = donors.get(receipt.donor)
		subject_type, subject_name = _donor_canonical_subject(donor) if donor else ("", "")
		if not subject_name:
			skipped.append(receipt.donor)
			continue
		details = frappe.parse_json(receipt.donation_details) or []
		row: dict[str, Any] = {
			"canonical_subject_type": subject_type,
			"canonical_subject": subject_name,
			"label": cstr(receipt.donor_name).strip() or cstr(donor.donor_name).strip() or subject_name,
			"donor": receipt.donor,
			"producer_context": {
				"tax_year": cstr(tax_year),
				"receipt_name": receipt.name,
				"receipt_total": fmt_money(flt(receipt.total_amount), currency=receipt.currency),
				"donation_count": cstr(cint(receipt.donation_count)),
				"donation_table_html": donation_table_html(details, receipt.currency),
			},
		}
		if donor.contact:
			row["contact"] = donor.contact
		if donor.customer:
			row["customer"] = donor.customer
		if language := cstr(donor.preferred_language).strip():
			row["language"] = language
		rows.append(row)

	if skipped:
		frappe.logger("non_profit").warning(
			f"Donation Tax Receipt provider skipped {len(skipped)} donor(s) "
			f"without a canonical postal subject for {reference}: {', '.join(sorted(skipped))}"
		)
	return rows


@frappe.whitelist(methods=["POST"])
def create_receipt_campaign(
	company: str,
	tax_year: int,
	letter_head: str,
	print_format: str | None = None,
	title: str | None = None,
	body_html: str | None = None,
	company_address: str | None = None,
) -> str:
	"""Generate the receipts, then open a postal Campaign for them.

	`title` and `body_html` override the German *letter* defaults (the Campaign
	itself is titled from the Company and tax year). Returns the created postal
	Campaign name.
	"""
	_require_dispatch_operator()
	if not frappe.db.exists("DocType", CAMPAIGN_DOCTYPE):
		frappe.throw(_("Postal donation tax receipts require the configured campaign integration."))
	company = _validated_company(company)
	tax_year = _validated_tax_year(tax_year)
	if not letter_head or not frappe.db.exists("Letter Head", letter_head):
		frappe.throw(_("Select an existing Letter Head for the receipt letters."))

	generate_receipts(company, tax_year)
	reference = receipt_campaign_reference(company, tax_year)
	existing_campaign = frappe.db.get_value(
		CAMPAIGN_DOCTYPE,
		{
			"source_provider": AUDIENCE_PROVIDER_KEY,
			"source_reference": reference,
			"status": ["!=", "Cancelled"],
		},
		["name", "status"],
		as_dict=True,
	)
	if existing_campaign:
		frappe.throw(
			_("Donation tax receipt Campaign {0} already exists with status {1}.").format(
				frappe.bold(existing_campaign.name), existing_campaign.status
			)
		)
	create_producer_campaign = frappe.get_attr(CREATE_PRODUCER_CAMPAIGN)
	return create_producer_campaign(
		AUDIENCE_PROVIDER_KEY,
		reference,
		{
			"title": _("Spendenbescheinigungen {0} - {1}").format(tax_year, company)[:140],
			"company": company,
			"letter_category": "Official",
			"include_payment_part": 0,
			"dispatch_channel": "manual_batch",
			"letter_head": letter_head,
			"company_address": company_address or _resolve_company_address(company),
			"main_language": "de",
			"language_formats": [
				{
					"language": "de",
					"print_format": print_format or DEFAULT_PRINT_FORMAT,
					"title": cstr(title).strip() or DEFAULT_LETTER_TITLE.format(tax_year),
					"body_html": cstr(body_html).strip() or DEFAULT_LETTER_BODY,
				}
			],
		},
	)


@frappe.whitelist(methods=["POST"])
def mark_receipts_issued(company: str, tax_year: int, receipt_names: str | list[str] | None = None) -> int:
	"""Mark selected Draft receipts as Issued.

	When names are omitted, only Draft receipts returned by the direct-mail
	provider are included, so subjectless donors are not marked as mailed.
	Operators can pass the explicit receipt names represented by a posted
	Campaign (or individually delivered receipts).
	"""
	_require_dispatch_operator()
	frappe.has_permission(RECEIPT_DOCTYPE, "write", throw=True)
	company = _validated_company(company)
	tax_year = _validated_tax_year(tax_year)
	_lock_generation_scope(company)
	names = _receipt_names_for_issue(company, tax_year, receipt_names)
	issued = 0
	for name in names:
		receipt = frappe.get_doc(RECEIPT_DOCTYPE, name, for_update=True)
		receipt.check_permission("write")
		if receipt.company != company or cint(receipt.tax_year) != tax_year:
			frappe.throw(_("Donation Tax Receipt {0} does not belong to the selected run.").format(name))
		if receipt.status != "Draft":
			continue
		receipt.status = "Issued"
		receipt.issued_on = nowdate()
		_authorize_receipt_service_write(receipt)
		receipt.save()
		issued += 1
	return issued


@frappe.whitelist(methods=["POST"])
def cancel_receipt(receipt: str, reason: str) -> dict[str, Any]:
	"""Cancel one Draft or Issued receipt with an immutable service audit."""
	_require_dispatch_operator()
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_("A cancellation reason is required."))

	current = frappe.get_doc(RECEIPT_DOCTYPE, receipt)
	current.check_permission("write")
	company = _validated_company(current.company)
	_lock_generation_scope(company)
	doc = frappe.get_doc(RECEIPT_DOCTYPE, receipt, for_update=True)
	doc.check_permission("write")
	if doc.status == "Cancelled":
		return {"receipt": doc.name, "status": doc.status, "changed": False}
	if doc.status not in ("Draft", "Issued"):
		frappe.throw(_("Only Draft or Issued Donation Tax Receipts can be cancelled."))
	doc.status = "Cancelled"
	doc.cancelled_on = now_datetime()
	doc.cancelled_by = frappe.session.user
	doc.cancellation_reason = reason
	_authorize_receipt_service_write(doc)
	doc.save()
	return {"receipt": doc.name, "status": doc.status, "changed": True}


@frappe.whitelist(methods=["POST"])
def send_receipt_email(receipt: str) -> dict[str, Any]:
	"""Email one Spendenbescheinigung as a PDF to its donor.

	This is the individual-issuance path ported from the retired `Donation
	Receipt.send_to_donor()`: same permission shape (document-level rights plus
	the DocType's email right), with the rendered PDF dispatched through the
	doc-referenced email provider seam and the same `email_sent_on` audit stamp.

	Emailing deliberately does **not** change the receipt status. `Issued` stays
	the explicit operator action performed by `mark_receipts_issued` once the
	annual batch is actually out; a Draft may be emailed as a courtesy copy
	without pretending the annual run happened.
	"""
	doc = frappe.get_doc(RECEIPT_DOCTYPE, receipt, for_update=True)
	# `run_doc_method`-style entry points only enforce read; sending mail on
	# behalf of the organisation and stamping an audit field needs the DocType's
	# explicit email right, exactly like the legacy receipt send action.
	doc.check_permission("read")
	doc.check_permission("email")

	if doc.status not in ("Draft", "Issued"):
		frappe.throw(_("Only Draft or Issued Donation Tax Receipts can be emailed."))

	# Channel preference (Phase 5): a donor explicitly preferring a registered
	# transactional channel receives the confirmation through it; everyone
	# else keeps the email path below.
	from non_profit.non_profit.channel_router import send_transactional

	if send_transactional("tax_confirmation", doc):
		return {
			"receipt": doc.name,
			"channel": "preferred",
			"print_format": None,
		}

	email = cstr(get_donor_email(doc.donor)).strip()
	if not email:
		frappe.throw(
			_("Donor {0} has no email address; the receipt cannot be emailed.").format(
				frappe.bold(doc.donor_name or doc.donor)
			)
		)

	print_format = _receipt_print_format(doc.company)
	# When Non Profit Settings asks for it, the PDF is password-protected before
	# it leaves — a receipt that reaches the wrong inbox stays unreadable there.
	from non_profit.non_profit.receipt_protection import receipt_password

	attachment = frappe.attach_print(
		doc.doctype,
		doc.name,
		print_format=print_format,
		lang=doc.language or "de",
		password=receipt_password(doc.donor),
	)
	email_queue = send_referenced_email(
		recipients=[email],
		subject=_("Spendenbescheinigung {0}").format(doc.tax_year),
		message=_receipt_email_body(doc),
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		attachments=[attachment],
	)
	send_queued_email_now(email_queue)
	doc.email_sent_on = now_datetime()
	_authorize_receipt_service_write(doc)
	doc.save()
	return {"receipt": doc.name, "email": email, "print_format": print_format}


def donor_address_lines(donor: str, company: str | None = None) -> list[str]:
	"""The donor's postal address, as the lines a receipt prints under the name.

	Exposed to Jinja (the `jinja.methods` hook) because § 50 EStDV requires the
	name *and* the address of the Zuwendender on a German Zuwendungsbestätigung
	— a "Name und Anschrift des Zuwendenden" row carrying only a name does not
	satisfy the form.

	The lookup is `receipt_protection._primary_address`, not a second query of
	its own: that helper already resolves Donor → Contact → Customer in the
	order a receipt wants, and it is the address whose postal code locks the
	PDF. Two independent lookups could disagree, and then the receipt would be
	addressed to one place and unlockable with the code of another.

	The country is printed only when it differs from the issuing company's, so
	a German receipt for a German donor keeps the plain two-line address the
	form expects.
	"""
	from non_profit.non_profit.receipt_protection import _primary_address

	address = _primary_address(donor)
	if not address:
		return []

	values = (
		frappe.db.get_value(
			"Address",
			address,
			["address_line1", "address_line2", "pincode", "city", "country"],
			as_dict=True,
		)
		or {}
	)

	lines = [cstr(values.get("address_line1")).strip(), cstr(values.get("address_line2")).strip()]
	locality = " ".join(
		part for part in (cstr(values.get("pincode")).strip(), cstr(values.get("city")).strip()) if part
	)
	lines.append(locality)

	country = cstr(values.get("country")).strip()
	issuer_country = cstr(frappe.db.get_value("Company", company, "country")).strip() if company else ""
	if country and country != issuer_country:
		lines.append(country)

	return [line for line in lines if line]


def _receipt_email_body(doc: Any) -> str:
	return (
		_(
			"<p>Guten Tag {0}</p>"
			"<p>Im Anhang finden Sie Ihre Spendenbescheinigung für das Steuerjahr {1}.</p>"
			"<p>Herzlichen Dank für Ihre Unterstützung.</p>"
		).format(escape_html(cstr(doc.donor_name or doc.donor)), cint(doc.tax_year))
		+ _protection_note()
	)


def _protection_note() -> str:
	"""Tell the recipient the attachment is locked, and what that does and does not buy.

	A password-protected PDF with no accompanying explanation is a support call:
	the donor cannot open their own receipt. The password is named by its
	*source* ("Ihre Postleitzahl"), never printed — the whole point is that a
	receipt delivered to the wrong inbox stays shut, and that only works while
	the reader does not already know the intended donor's postal code.

	The honesty about transport is deliberate. This is access protection on the
	attachment, not encryption in transit: the mail still travels as ordinary
	SMTP. Saying so is what lets a donor who needs more ask for another channel.
	See `non_profit.non_profit.receipt_protection`.
	"""
	from non_profit.non_profit.receipt_protection import (
		DEFAULT_PASSWORD_SOURCE,
		receipt_protection_enabled,
	)

	if not receipt_protection_enabled():
		return ""

	source = (
		frappe.db.get_single_value("Non Profit Settings", "receipt_pdf_password_source")
		or DEFAULT_PASSWORD_SOURCE
	)
	key = (
		_("Ihre Postleitzahl")
		if source == "Postal Code"
		else _("Ihre Spendernummer, die Sie auf früheren Bescheinigungen finden")
	)

	return _(
		"<hr>"
		"<p><strong>Hinweis zum Datenschutz</strong></p>"
		"<p>Das angehängte PDF ist mit einem Passwort geschützt. Das Passwort ist {0}. "
		"So bleibt Ihre Bescheinigung auch dann unlesbar, wenn diese E-Mail versehentlich "
		"an den falschen Empfänger gerät.</p>"
		"<p>Bitte beachten Sie: Der Passwortschutz sichert den Anhang, nicht den Transportweg. "
		"Eine gewöhnliche E-Mail wird unverschlüsselt übertragen. Wenn Sie eine verschlüsselte "
		"Übermittlung wünschen, antworten Sie uns bitte — wir senden Ihnen die Bescheinigung "
		"dann per Post oder über einen gesicherten Kanal zu.</p>"
	).format(key)


def _receipt_print_format(company: str | None = None) -> str:
	print_format = receipt_print_format_for(company)
	values = frappe.db.get_value("Print Format", print_format, ["doc_type", "disabled"], as_dict=True)
	if not values or values.doc_type != RECEIPT_DOCTYPE or values.disabled:
		frappe.throw(
			_("The {0} Print Format is missing or disabled; run a bench migrate to restore it.").format(
				frappe.bold(print_format)
			)
		)
	return print_format


def donation_table_html(details: list[dict[str, Any]], currency: str | None = None) -> str:
	"""Build the de-locale date/amount table handed to the letter as trusted markup."""
	currency = currency or DEFAULT_RECEIPT_CURRENCY
	rows = "".join(
		'<tr><td>{0}</td><td style="text-align:right">{1}</td></tr>'.format(
			escape_html(formatdate(row.get("date"), "dd.MM.yyyy")),
			escape_html(fmt_money(flt(row.get("amount")), currency=currency)),
		)
		for row in details
	)
	return (
		'<table class="donation-tax-receipt-table">'
		"<thead><tr><th>Datum</th><th>Betrag</th></tr></thead>"
		f"<tbody>{rows}</tbody></table>"
	)


def _lock_generation_scope(company: str) -> None:
	"""Serialize receipt runs on an existing Company row until transaction end.

	The Company row exists even when the year has no Donations or receipts, unlike
	an empty naming-series row. Every receipt mutation takes this lock before any
	Donation or receipt row locks, which gives the service one deterministic lock
	order and prevents duplicate first-run inserts.
	"""
	company_doctype = frappe.qb.DocType("Company")
	locked = (
		frappe.qb.from_(company_doctype)
		.select(company_doctype.name)
		.where(company_doctype.name == company)
		.orderby(company_doctype.name)
		.for_update()
	).run(pluck=True)
	if locked != [company]:
		frappe.throw(_("Company {0} does not exist.").format(company))


def _locked_existing_receipts(company: str, tax_year: int) -> list[Any]:
	filters = {"company": company, "tax_year": tax_year}
	permitted_names = set(
		frappe.get_list(
			RECEIPT_DOCTYPE,
			filters=filters,
			pluck="name",
			order_by="name asc",
			limit=0,
		)
	)
	all_names = set(frappe.get_all(RECEIPT_DOCTYPE, filters=filters, pluck="name", limit=0))
	if all_names != permitted_names:
		frappe.throw(
			_("You do not have permission to read the complete Donation Tax Receipt run."),
			frappe.PermissionError,
		)
	if not permitted_names:
		return []

	receipt = frappe.qb.DocType(RECEIPT_DOCTYPE)
	return (
		frappe.qb.from_(receipt)
		.select(
			receipt.name,
			receipt.donor,
			receipt.status,
			receipt.total_amount,
			receipt.donation_count,
			receipt.donation_details,
		)
		.where(receipt.name.isin(sorted(permitted_names)))
		.orderby(receipt.name)
		.for_update()
	).run(as_dict=True)


def _receipt_names_for_issue(company: str, tax_year: int, receipt_names: str | list[str] | None) -> list[str]:
	if receipt_names is None:
		rows = direct_mail_candidate_rows(receipt_campaign_reference(company, tax_year))
		return sorted(row["producer_context"]["receipt_name"] for row in rows)

	values = frappe.parse_json(receipt_names) if isinstance(receipt_names, str) else receipt_names
	if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
		frappe.throw(_("Receipt Names must be a JSON list of Donation Tax Receipt names."))
	return sorted({cstr(value).strip() for value in values if cstr(value).strip()})


def _qualifying_donations(company: str, tax_year: int) -> dict[str, list[dict[str, Any]]]:
	filters = {
		"docstatus": 1,
		"paid": 1,
		"company": company,
		"date": ["between", (f"{tax_year}-01-01", f"{tax_year}-12-31")],
		"amount": [">", 0],
		"donor": ["is", "set"],
	}
	donations = frappe.get_list(
		"Donation",
		filters=filters,
		fields=["name", "donor", "date", "amount"],
		order_by="name asc",
		limit=0,
	)
	all_names = set(frappe.get_all("Donation", filters=filters, pluck="name", limit=0))
	permitted_names = {row.name for row in donations}
	if all_names != permitted_names:
		frappe.throw(
			_("You do not have permission to read the complete set of qualifying Donations."),
			frappe.PermissionError,
		)
	if not permitted_names:
		return {}

	donation = frappe.qb.DocType("Donation")
	donations = (
		frappe.qb.from_(donation)
		.select(
			donation.name,
			donation.donor,
			donation.date,
			donation.amount,
			donation.company,
			donation.docstatus,
			donation.paid,
		)
		.where(donation.name.isin(sorted(permitted_names)))
		.orderby(donation.name)
		.for_update()
	).run(as_dict=True)
	start_date = getdate(f"{tax_year}-01-01")
	end_date = getdate(f"{tax_year}-12-31")
	donations = [
		row
		for row in donations
		if row.company == company
		and cint(row.docstatus) == 1
		and cint(row.paid) == 1
		and row.donor
		and flt(row.amount) > 0
		and start_date <= getdate(row.date) <= end_date
	]
	donations.sort(key=lambda row: (row.donor, getdate(row.date), row.name))
	grouped: dict[str, list[dict[str, Any]]] = {}
	for row in donations:
		grouped.setdefault(row.donor, []).append(
			{"donation": row.name, "date": cstr(row.date), "amount": flt(row.amount)}
		)
	return grouped


def _insert_draft_receipt(
	company: str, tax_year: int, donor: str, details: list[dict[str, Any]], total: float
) -> None:
	receipt = frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"donor": donor,
			"tax_year": tax_year,
			"company": company,
			"currency": receipt_currency(company),
			"status": "Draft",
			"total_amount": total,
			"donation_count": len(details),
			"donation_details": frappe.as_json(details),
		}
	)
	_authorize_receipt_service_write(receipt)
	receipt.insert()


def _update_draft_receipt(name: str, details: list[dict[str, Any]], total: float) -> None:
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name, for_update=True)
	if receipt.status != "Draft":
		frappe.throw(_("Only Draft Donation Tax Receipts can be refreshed."))
	receipt.total_amount = total
	receipt.donation_count = len(details)
	receipt.donation_details = frappe.as_json(details)
	_authorize_receipt_service_write(receipt)
	receipt.save()


def _delete_draft_receipt(name: str) -> None:
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name, for_update=True)
	if receipt.status != "Draft":
		frappe.throw(_("Only stale Draft Donation Tax Receipts can be deleted."))
	_authorize_receipt_service_write(receipt)
	receipt.delete()


def _receipt_matches(record: Any, details: list[dict[str, Any]], total: float) -> bool:
	return (
		flt(record.total_amount) == total
		and cint(record.donation_count) == len(details)
		and (frappe.parse_json(record.donation_details) or []) == details
	)


def _parse_reference(reference: str) -> tuple[str, int]:
	company, separator, raw_year = cstr(reference).rpartition("|")
	if not separator or not company.strip():
		frappe.throw(_("Donation Tax Receipt reference must be '<company>|<tax_year>'."))
	return _validated_company(company.strip()), _validated_tax_year(raw_year)


def _validated_company(company: str) -> str:
	company = cstr(company).strip()
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist.").format(company or _("(blank)")))
	frappe.has_permission("Company", "read", doc=company, throw=True)
	if not frappe.get_cached_value("Company", company, "default_currency"):
		frappe.throw(
			_("Company {0} has no default currency, so receipt amounts cannot be issued.").format(
				frappe.bold(company)
			)
		)
	return company


def _validated_tax_year(tax_year: Any) -> int:
	year = cint(tax_year)
	if not MIN_TAX_YEAR <= year <= MAX_TAX_YEAR:
		frappe.throw(_("Tax Year must be between {0} and {1}.").format(MIN_TAX_YEAR, MAX_TAX_YEAR))
	return year


def _resolve_company_address(company: str) -> str:
	links = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": "Company", "link_name": company},
		pluck="parent",
		limit=0,
	)
	addresses = frappe.get_all(
		"Address",
		filters={"name": ["in", sorted(set(links))], "disabled": 0},
		fields=["name", "is_primary_address"],
		order_by="name asc",
		limit=0,
	)
	if len(addresses) == 1:
		return addresses[0].name
	primary = [row.name for row in addresses if cint(row.is_primary_address)]
	if len(primary) == 1:
		return primary[0]
	frappe.throw(_("Select an explicit Company Address for {0}.").format(company))


def _require_dispatch_operator() -> None:
	roles = set(frappe.get_roles())
	allowed = {role for role in DISPATCH_ROLES if frappe.db.exists("Role", role)}
	if not roles & allowed:
		frappe.throw(
			_("Not permitted to run donation tax receipt dispatch operations."),
			frappe.PermissionError,
		)
