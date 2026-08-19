from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint

# Receipts are issued in the currency of the issuing Company. The constant is
# the fallback for a receipt that has no company yet, and the historical Swiss
# default; it is no longer a restriction.
DEFAULT_RECEIPT_CURRENCY = "CHF"
RECEIPT_STATUSES = ("Draft", "Issued", "Cancelled")
RECEIPT_LANGUAGES = ("de", "fr", "it", "en")
DEFAULT_RECEIPT_LANGUAGE = "de"
MIN_TAX_YEAR = 2000
MAX_TAX_YEAR = 2100

# Capability sentinel: the write guard compares by object identity, so a
# request-supplied flag value can never authorize official receipt content.
_RECEIPT_SERVICE_WRITE = object()
SERVICE_CONTROLLED_FIELDS = frozenset(
	{
		"donor",
		"donor_name",
		"tax_year",
		"company",
		"currency",
		"status",
		"issued_on",
		"cancelled_on",
		"cancelled_by",
		"cancellation_reason",
		"email_sent_on",
		"total_amount",
		"donation_count",
		"donation_details",
	}
)


def _authorize_receipt_service_write(doc) -> None:
	doc.flags.donation_tax_receipt_service_write = _RECEIPT_SERVICE_WRITE


def is_receipt_service_write(doc) -> bool:
	return doc.flags.get("donation_tax_receipt_service_write") is _RECEIPT_SERVICE_WRITE


def receipt_currency(company: str | None) -> str:
	"""The currency a receipt for `company` is issued in."""
	if not company:
		return DEFAULT_RECEIPT_CURRENCY
	return frappe.get_cached_value("Company", company, "default_currency") or DEFAULT_RECEIPT_CURRENCY


class DonationTaxReceipt(Document):
	def before_naming(self) -> None:
		# Reject unauthorized inserts before they consume an official series value.
		self._validate_service_controlled_write()

	def autoname(self) -> None:
		tax_year = cint(self.tax_year)
		if not MIN_TAX_YEAR <= tax_year <= MAX_TAX_YEAR:
			frappe.throw(_("Tax Year must be between {0} and {1}.").format(MIN_TAX_YEAR, MAX_TAX_YEAR))
		self.name = make_autoname(f"NPO-STR-{tax_year}-.#####")

	def validate(self) -> None:
		self._validate_service_controlled_write()
		company_currency = receipt_currency(self.company)
		self.currency = self.currency or company_currency
		if self.company and self.currency != company_currency:
			frappe.throw(
				_("Donation Tax Receipts are issued in the Company currency ({0}), not {1}.").format(
					company_currency, self.currency
				)
			)
		tax_year = cint(self.tax_year)
		if not MIN_TAX_YEAR <= tax_year <= MAX_TAX_YEAR:
			frappe.throw(
				_("Tax Year must be between {0} and {1}.").format(MIN_TAX_YEAR, MAX_TAX_YEAR),
			)
		self.tax_year = tax_year
		self.language = (self.language or DEFAULT_RECEIPT_LANGUAGE).strip().lower()
		if self.language not in RECEIPT_LANGUAGES:
			frappe.throw(_("Language must be one of {0}.").format(", ".join(RECEIPT_LANGUAGES)))
		self.status = self.status or "Draft"
		if self.status not in RECEIPT_STATUSES:
			frappe.throw(_("Status must be Draft, Issued, or Cancelled."))
		if self.status == "Draft":
			self.issued_on = None
		if self.status == "Issued" and not self.issued_on:
			frappe.throw(_("An Issued Donation Tax Receipt requires an issue date."))
		if self.status != "Cancelled" and any(
			(self.cancelled_on, self.cancelled_by, self.cancellation_reason)
		):
			frappe.throw(_("Cancellation audit fields require Cancelled status."))

	def _validate_service_controlled_write(self) -> None:
		if is_receipt_service_write(self):
			return
		old = self.get_doc_before_save()
		if not old:
			frappe.throw(_("Donation Tax Receipts can only be created by the receipt service."))
		changed = sorted(
			fieldname for fieldname in SERVICE_CONTROLLED_FIELDS if self.get(fieldname) != old.get(fieldname)
		)
		if changed:
			frappe.throw(_("Use the Donation Tax Receipt service to change: {0}.").format(", ".join(changed)))

	def on_trash(self) -> None:
		if not is_receipt_service_write(self):
			frappe.throw(_("Donation Tax Receipts can only be deleted by the receipt service."))
		if self.status != "Draft":
			frappe.throw(_("Only stale Draft Donation Tax Receipts can be deleted."))


def on_doctype_update() -> None:
	frappe.db.add_unique(
		"Donation Tax Receipt",
		["donor", "tax_year", "company"],
		constraint_name="unique_donor_tax_year_company",
	)
