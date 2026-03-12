# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_company_address
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form

from erpnext.accounts.utils import get_fiscal_year
from non_profit.non_profit.doctype.member.member import get_member_email


class TaxExemption80GCertificate(Document):
    def validate(self):
        self.validate_duplicates()
        self.validate_company_details()
        self.set_member_details()
        self.set_company_address()
        self.calculate_total()
        self.set_title()

    def set_member_details(self):
        if self.recipient != "Member" or not self.member:
            self.member_email = ""
            self.member_pan_number = ""
            return

        member_customer = frappe.db.get_value("Member", self.member, "customer")
        self.member_email = get_member_email(self.member) or ""
        self.member_pan_number = (
            frappe.db.get_value("Customer", member_customer, "tax_id") or ""
        )

    def validate_duplicates(self):
        if self.recipient == "Donor":
            certificate = frappe.db.exists(
                self.doctype, {"donation": self.donation, "name": ("!=", self.name)}
            )
            if certificate:
                frappe.throw(
                    _(
                        "An 80G Certificate {0} already exists for the donation {1}"
                    ).format(
                        get_link_to_form(self.doctype, certificate),
                        frappe.bold(self.donation),
                    ),
                    title=_("Duplicate Certificate"),
                )

    def validate_company_details(self):
        fields = ["company_80g_number", "with_effect_from", "pan_details"]
        company_details = frappe.db.get_value(
            "Company", self.company, fields, as_dict=True
        )
        if not company_details.company_80g_number:
            frappe.throw(
                _("Please set the {0} for company {1}").format(
                    frappe.bold("80G Number"), get_link_to_form("Company", self.company)
                )
            )

        if not company_details.pan_details:
            frappe.throw(
                _("Please set the {0} for company {1}").format(
                    frappe.bold("PAN Number"), get_link_to_form("Company", self.company)
                )
            )

    @frappe.whitelist()
    def set_company_address(self):
        address = get_company_address(self.company)
        self.company_address = address.company_address
        self.company_address_display = address.company_address_display

    def calculate_total(self):
        if self.recipient == "Donor":
            return

        total = 0
        for entry in self.payments:
            total += flt(entry.amount)
        self.total = total

    def set_title(self):
        if self.recipient == "Member":
            self.title = self.member_name
        else:
            self.title = self.donor_name

    @frappe.whitelist()
    def get_payments(self):
        if not self.member:
            frappe.throw(_("Please select a Member first."))

        fiscal_year = get_fiscal_year(fiscal_year=self.fiscal_year, as_dict=True)

        memberships = frappe.db.get_all(
            "Membership",
            {
                "member": self.member,
                "docstatus": 1,
            },
            ["name", "membership_type", "subscription", "customer"],
            order_by="creation",
        )

        if not memberships:
            frappe.msgprint(
                _("No Membership Payments found against the Member {0}").format(
                    self.member
                )
            )

        total = 0
        self.payments = []

        for membership in memberships:
            invoices = self.get_membership_invoices_for_fiscal_year(
                membership, fiscal_year.year_start_date, fiscal_year.year_end_date
            )
            for invoice in invoices:
                self.append(
                    "payments",
                    {
                        "date": invoice.posting_date,
                        "amount": invoice.grand_total,
                        "invoice_id": invoice.name,
                        "payment_id": invoice.name,
                        "membership": membership.name,
                    },
                )
                total += flt(invoice.grand_total)

        self.total = total

    def get_membership_invoices_for_fiscal_year(
        self, membership, year_start_date, year_end_date
    ):
        filters = {
            "docstatus": 1,
            "posting_date": ["between", (year_start_date, year_end_date)],
        }

        if membership.subscription:
            filters["subscription"] = membership.subscription
        else:
            filters["customer"] = membership.customer

        return frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=["name", "posting_date", "grand_total"],
            order_by="posting_date",
        )
