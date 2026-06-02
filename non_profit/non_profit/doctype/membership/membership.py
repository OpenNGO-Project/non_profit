# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    add_days,
    add_months,
    add_years,
    get_link_to_form,
    getdate,
    nowdate,
)


class Membership(Document):
    def validate(self):
        # Member is the canonical identity for a Membership. For B2B flows,
        # create the Member up front (pointing at the Customer) before binding
        # a Membership to it.
        if not self.member or not frappe.db.exists("Member", self.member):
            user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
            if user_type == "Website User":
                self.create_member_from_website_user()
            else:
                frappe.throw(_("Please select a Member"))

        self.validate_membership_period()

    def create_member_from_website_user(self):
        member_name = frappe.get_value("Member", dict(email_id=frappe.session.user))

        if not member_name:
            user = frappe.get_doc("User", frappe.session.user)
            member = frappe.get_doc(
                dict(
                    doctype="Member",
                    email_id=frappe.session.user,
                    membership_type=self.membership_type,
                    member_name=user.get_fullname(),
                )
            ).insert(ignore_permissions=True)
            member_name = member.name

        if self.get("__islocal"):
            self.member = member_name

    def validate_membership_period(self):
        last_membership = get_last_membership(self.member)

        if (
            last_membership
            and last_membership.name != self.name
            and frappe.session.user != "Administrator"
            and last_membership.to_date
        ):
            if getdate(add_days(last_membership.to_date, -30)) > getdate(nowdate()):
                frappe.throw(
                    _("You can only renew if your membership expires within 30 days")
                )

            self.from_date = add_days(last_membership.to_date, 1)

        # Public/client apps may explicitly request an open-ended membership.
        # Keep that generic signal here so presentation apps do not need to
        # fight the default billing-cycle date fill after insert.
        if not self.to_date and not getattr(self.flags, "keep_to_date_open", False):
            billing_cycle = frappe.db.get_single_value(
                "Non Profit Settings", "billing_cycle"
            )
            if billing_cycle == "Yearly":
                self.to_date = add_years(self.from_date, 1)
            elif billing_cycle == "Monthly":
                self.to_date = add_months(self.from_date, 1)

    def on_payment_authorized(self, status_changed_to=None):
        if status_changed_to not in ("Completed", "Authorized"):
            return
        self.load_from_db()
        # `paid` column was dropped in the B2B/B2C schema refactor (a58cc79);
        # payment state lives on the linked Sales Invoice now.
        settings = frappe.get_doc("Non Profit Settings")
        if settings.allow_invoicing and settings.automate_membership_invoicing:
            self.generate_invoice(
                with_payment_entry=settings.automate_membership_payment_entries,
                save=True,
            )

    @frappe.whitelist()
    def generate_invoice(
        self, save: bool = True, with_payment_entry: bool = False
    ) -> Any:
        if not (self.currency or self.amount):
            frappe.throw(
                _(
                    "The payment for this membership is not paid. To generate invoice fill the payment details"
                )
            )

        if self.invoice:
            frappe.throw(_("An invoice is already linked to this document"))

        member = frappe.get_doc("Member", self.member)
        if not member.customer:
            frappe.throw(
                _("No customer linked to member {0}").format(frappe.bold(self.member))
            )

        plan = frappe.get_doc("Membership Type", self.membership_type)
        settings = frappe.get_doc("Non Profit Settings")
        self.validate_membership_type_and_settings(plan, settings)

        invoice = make_invoice(self, member, plan, settings)
        self.reload()
        self.invoice = invoice.name

        if with_payment_entry:
            self.make_payment_entry(settings, invoice)

        if save:
            self.save()

        return invoice

    def validate_membership_type_and_settings(self, plan, settings):
        settings_link = get_link_to_form("Non Profit Settings", "Non Profit Settings")

        if not settings.membership_debit_account:
            frappe.throw(
                _("You need to set <b>Debit Account</b> in {0}").format(settings_link)
            )

        if not settings.company:
            frappe.throw(
                _("You need to set <b>Default Company</b> for invoicing in {0}").format(
                    settings_link
                )
            )

        if not plan.linked_item:
            frappe.throw(
                _("Please set a Linked Item for the Membership Type {0}").format(
                    get_link_to_form("Membership Type", self.membership_type)
                )
            )

    def make_payment_entry(self, settings, invoice):
        if not settings.membership_payment_account:
            frappe.throw(
                _(
                    "You need to set <b>Payment Account</b> for Membership in {0}"
                ).format(get_link_to_form("Non Profit Settings", "Non Profit Settings"))
            )

        from erpnext.accounts.doctype.payment_entry.payment_entry import (
            get_payment_entry,
        )

        frappe.flags.ignore_account_permission = True
        pe = get_payment_entry(
            dt="Sales Invoice", dn=invoice.name, bank_amount=invoice.grand_total
        )
        frappe.flags.ignore_account_permission = False
        pe.paid_to = settings.membership_payment_account
        pe.reference_no = self.name
        pe.reference_date = getdate()
        pe.flags.ignore_mandatory = True
        pe.save()
        pe.submit()

    @frappe.whitelist()
    def send_acknowlement(self) -> None:
        settings = frappe.get_doc("Non Profit Settings")
        if not settings.send_email:
            frappe.throw(
                _("You need to enable <b>Send Acknowledge Email</b> in {0}").format(
                    get_link_to_form("Non Profit Settings", "Non Profit Settings")
                )
            )

        member = frappe.get_doc("Member", self.member)
        if not member.email_id:
            frappe.throw(
                _("Email address of member {0} is missing").format(
                    frappe.utils.get_link_to_form("Member", self.member)
                )
            )

        email = member.email_id
        attachments = [
            frappe.attach_print(
                "Membership", self.name, print_format=settings.membership_print_format
            )
        ]

        if self.invoice and settings.send_invoice:
            attachments.append(
                frappe.attach_print(
                    "Sales Invoice",
                    self.invoice,
                    print_format=settings.inv_print_format,
                )
            )

        email_template = frappe.get_doc("Email Template", settings.email_template)
        context = {"doc": self, "member": member}

        email_args = {
            "recipients": [email],
            "message": frappe.render_template(email_template.get("response"), context),
            "subject": frappe.render_template(email_template.get("subject"), context),
            "attachments": attachments,
            "reference_doctype": self.doctype,
            "reference_name": self.name,
        }

        if not frappe.flags.in_test:
            frappe.enqueue(
                method=frappe.sendmail,
                queue="short",
                timeout=300,
                is_async=True,
                **email_args,
            )
        else:
            frappe.sendmail(**email_args)

    def generate_and_send_invoice(self):
        self.generate_invoice(save=False)
        self.send_acknowlement()


def make_invoice(membership, member, plan, settings):
    invoice = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "customer": member.customer,
            "debit_to": settings.membership_debit_account,
            "currency": membership.currency,
            "company": settings.company,
            "is_pos": 0,
            "items": [
                {"item_code": plan.linked_item, "rate": membership.amount, "qty": 1}
            ],
        }
    )
    invoice.set_missing_values()
    invoice.insert()
    invoice.submit()

    frappe.msgprint(_("Sales Invoice created successfully"))

    return invoice


def get_company_for_memberships():
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if not company:
        from non_profit.non_profit.utils import get_company

        company = get_company()
    return company


def set_expired_status():
    membership = frappe.qb.DocType("Membership")
    (
        frappe.qb.update(membership)
        .set(membership.membership_status, "Expired")
        .where(membership.membership_status.notin(("Cancelled", "Expired")))
        .where(membership.to_date < nowdate())
    ).run()


def get_last_membership(member):
    """Returns last membership if exists"""
    if not member:
        return None
    # `paid=1` filter dropped — column removed in B2B/B2C refactor (a58cc79);
    # payment state lives on Sales Invoice.
    last_membership = frappe.get_all(
        "Membership",
        "name,to_date,membership_type",
        dict(member=member),
        order_by="to_date desc",
        limit=1,
    )

    if last_membership:
        return last_membership[0]
