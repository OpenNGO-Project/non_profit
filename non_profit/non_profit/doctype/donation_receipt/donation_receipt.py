from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import GroupConcat
from frappe.utils import flt, nowdate

from non_profit.non_profit.doctype.donor.donor import get_donor_email

DEFAULT_RECEIPT_COUNTRY = "Switzerland"


class DonationReceipt(Document):
    def validate(self):
        if self.donor:
            self.email = get_donor_email(self.donor) or self.email
        self._fill_donation_rows()
        self._compute_total()
        if self.fiscal_year and not self.period_from:
            fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
            self.period_from = fy.year_start_date
            self.period_to = fy.year_end_date

    def _fill_donation_rows(self):
        for row in self.donations or []:
            if not row.donation:
                continue
            donation = frappe.db.get_value(
                "Donation",
                row.donation,
                ["date", "amount"],
                as_dict=True,
            )
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
        self._validate_donations_for_submit()
        self.status = "Issued"
        self.issued_on = nowdate()
        self.issued_by = frappe.session.user
        self._mark_donations()

    def _validate_donations_for_submit(self):
        donation_names = [row.donation for row in self.donations or [] if row.donation]
        if not donation_names:
            frappe.throw(_("Add at least one Donation before submitting the receipt."))

        seen = set()
        for donation_name in donation_names:
            if donation_name in seen:
                frappe.throw(_("Donation {0} is listed more than once.").format(frappe.bold(donation_name)))
            seen.add(donation_name)
            donation = frappe.db.get_value(
                "Donation",
                donation_name,
                ["donor", "docstatus", "paid", "date", "receipt"],
                as_dict=True,
            )
            if not donation:
                frappe.throw(_("Donation {0} does not exist.").format(frappe.bold(donation_name)))
            if donation.donor != self.donor:
                frappe.throw(_("Donation {0} belongs to another donor.").format(frappe.bold(donation_name)))
            if donation.docstatus != 1:
                frappe.throw(_("Donation {0} must be submitted.").format(frappe.bold(donation_name)))
            if not donation.paid:
                frappe.throw(_("Donation {0} must be paid.").format(frappe.bold(donation_name)))
            if self.period_from and donation.date and donation.date < self.period_from:
                frappe.throw(_("Donation {0} is outside the receipt period.").format(frappe.bold(donation_name)))
            if self.period_to and donation.date and donation.date > self.period_to:
                frappe.throw(_("Donation {0} is outside the receipt period.").format(frappe.bold(donation_name)))
            if donation.receipt and donation.receipt != self.name:
                frappe.throw(_("Donation {0} already has a receipt.").format(frappe.bold(donation_name)))
            other_receipt = _active_receipt_for_donation(donation_name, self.name)
            if other_receipt:
                frappe.throw(
                    _("Donation {0} is already linked to receipt {1}.").format(
                        frappe.bold(donation_name), frappe.bold(other_receipt)
                    )
                )

    def _mark_donations(self):
        for row in self.donations or []:
            if row.donation:
                frappe.db.set_value("Donation", row.donation, "receipt", self.name)

    def on_cancel(self):
        self.status = "Cancelled"
        for row in self.donations or []:
            if row.donation and frappe.db.get_value("Donation", row.donation, "receipt") == self.name:
                frappe.db.set_value("Donation", row.donation, "receipt", None)

    @frappe.whitelist()
    def send_to_donor(self) -> bool:
        self.check_permission("write")
        if not self.email:
            frappe.throw(_("No donor email"))
        frappe.sendmail(
            recipients=[self.email],
            subject=f"Zuwendungsbestätigung {self.fiscal_year}",
            message=self._get_email_body(),
            attachments=[
                frappe.attach_print(
                    self.doctype, self.name, print_format="Donation Receipt DE"
                )
            ],
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
    donation = frappe.qb.DocType("Donation")
    rows = (
        frappe.qb.from_(donation)
        .select(
            donation.donor,
            GroupConcat(donation.name).as_("donation_names"),
        )
        .where(donation.docstatus == 1)
        .where(donation.paid == 1)
        .where((donation.date >= start) & (donation.date <= end))
        .where(donation.donor.isnotnull())
        .where((donation.receipt.isnull()) | (donation.receipt == ""))
        .groupby(donation.donor)
    ).run(as_dict=True)
    created = []
    for row in rows:
        if not row.donor:
            continue
        donation_names = [n for n in (row.donation_names or "").split(",") if n]
        linked_donations = _donations_linked_to_active_receipts(donation_names)
        donation_names = [name for name in donation_names if name not in linked_donations]
        if not donation_names:
            continue
        receipt = frappe.get_doc(
            {
                "doctype": "Donation Receipt",
                "donor": row.donor,
                "fiscal_year": fiscal_year,
                "period_from": start,
                "period_to": end,
                "country": country,
                "language": language,
                "donations": [_donation_receipt_row(n) for n in donation_names],
            }
        )
        receipt.flags.ignore_permissions = True
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
    donations = frappe.get_list(
        "Donation",
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
        limit_page_length=0,
    )
    linked_donations = _donations_linked_to_active_receipts([donation.name for donation in donations])
    rows = [
        {
            "donation": donation.name,
            "donation_date": donation.date,
            "amount": donation.amount,
        }
        for donation in donations
        if donation.name not in linked_donations
    ]
    return {"count": len(rows), "donations": rows}


def _active_receipt_for_donation(donation_name: str, current_receipt: str | None = None) -> str | None:
    receipt_names = frappe.get_all(
        "Donation Receipt Item",
        filters={
            "donation": donation_name,
            "parenttype": "Donation Receipt",
            "parent": ["!=", current_receipt or ""],
        },
        pluck="parent",
    )
    if not receipt_names:
        return None
    return frappe.db.get_value(
        "Donation Receipt",
        {"name": ["in", receipt_names], "docstatus": ["<", 2]},
        "name",
    )


def _donations_linked_to_active_receipts(donation_names: list[str]) -> set[str]:
    donation_names = [name for name in donation_names if name]
    if not donation_names:
        return set()
    rows = frappe.get_all(
        "Donation Receipt Item",
        filters={
            "donation": ["in", donation_names],
            "parenttype": "Donation Receipt",
        },
        fields=["donation", "parent"],
        limit_page_length=0,
    )
    receipt_names = sorted({row.parent for row in rows if row.parent})
    if not receipt_names:
        return set()
    active_receipts = set(
        frappe.get_all(
            "Donation Receipt",
            filters={"name": ["in", receipt_names], "docstatus": ["<", 2]},
            pluck="name",
            limit_page_length=0,
        )
    )
    return {row.donation for row in rows if row.parent in active_receipts}


def _donation_receipt_row(donation_name: str) -> dict[str, Any]:
    donation = frappe.db.get_value(
        "Donation",
        donation_name,
        ["date", "amount"],
        as_dict=True,
    ) or {}
    return {
        "donation": donation_name,
        "donation_date": donation.get("date"),
        "amount": donation.get("amount"),
    }


def _default_receipt_country() -> str:
    if frappe.db.exists("Country", DEFAULT_RECEIPT_COUNTRY):
        return DEFAULT_RECEIPT_COUNTRY
    return frappe.db.get_default("country") or frappe.db.get_value(
        "Country", {}, "name", order_by="name asc"
    )


def _require_receipt_manager() -> None:
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.intersection({"System Manager", "Non Profit Manager"}):
        return
    frappe.throw(_("Not permitted"), frappe.PermissionError)
