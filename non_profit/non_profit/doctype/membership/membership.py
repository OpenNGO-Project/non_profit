import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from non_profit.non_profit.doctype.member.member import (
    get_customer_primary_contact,
    get_member_contact,
    is_contact_linked_to_customer,
)


class Membership(Document):
    def onload(self):
        """Sync subscription status on load."""
        self.sync_status_from_subscription()

    def validate(self):
        if not self.member:
            frappe.throw(_("Member is required"))

        member_customer = frappe.db.get_value("Member", self.member, "customer")
        if not member_customer:
            frappe.throw(
                _(
                    "Member {0} does not have a Customer linked. Please link a Customer to the Member first."
                ).format(self.member)
            )

        self.set_billing_details(member_customer)
        self.validate_billing_details()

        if not self.member_since_date:
            self.member_since_date = getdate()

        self.validate_duplicate_membership()

    def set_billing_details(self, member_customer):
        if not self.customer:
            self.customer = member_customer

        if not self.contact:
            default_contact = self.get_default_billing_contact(member_customer)
            if default_contact:
                self.contact = default_contact.name

    def get_default_billing_contact(self, member_customer=None):
        member_customer = member_customer or frappe.db.get_value(
            "Member", self.member, "customer"
        )

        if self.customer == member_customer:
            return get_member_contact(self.member) or get_customer_primary_contact(
                self.customer
            )

        return get_customer_primary_contact(self.customer)

    def validate_billing_details(self):
        if not self.customer:
            frappe.throw(_("Billing Customer is required"))

        if not self.contact:
            frappe.throw(_("Billing Contact is required"))

        if not is_contact_linked_to_customer(self.contact, self.customer):
            frappe.throw(
                _("Billing Contact must be linked to Billing Customer {0}.").format(
                    frappe.bold(self.customer)
                )
            )

    @frappe.whitelist()
    def get_billing_details(self):
        member_customer = frappe.db.get_value("Member", self.member, "customer")
        customer = self.customer or member_customer
        contact = None

        if customer:
            if customer == member_customer:
                contact = get_member_contact(
                    self.member
                ) or get_customer_primary_contact(customer)
            else:
                contact = get_customer_primary_contact(customer)

        return {
            "customer": customer or "",
            "contact": contact.name if contact else "",
        }

    def validate_duplicate_membership(self):
        """Check for duplicate active membership of same type."""
        if self.is_new() or not self.name:
            filters = {
                "member": self.member,
                "membership_type": self.membership_type,
                "docstatus": 1,
            }
            existing = frappe.db.exists("Membership", filters)
            if existing:
                frappe.throw(
                    _("Member already has an active membership of type {0}").format(
                        self.membership_type
                    )
                )

    def on_submit(self):
        if self.auto_renew:
            self.create_subscription()

    def on_cancel(self):
        self.cancel_subscription()

    def on_update_after_submit(self):
        self.sync_status_from_subscription()

    def create_subscription(self):
        """Create an ERPNext Subscription for this membership."""
        if not self.customer:
            frappe.throw(_("Membership does not have a Billing Customer linked"))

        subscription_plan = frappe.db.get_value(
            "Membership Type", self.membership_type, "subscription_plan"
        )

        if not subscription_plan:
            frappe.msgprint(
                _(
                    "No Subscription Plan linked to Membership Type. "
                    "Please save the Membership Type to auto-create one."
                )
            )
            return

        if self.subscription:
            frappe.msgprint(
                _("This membership already has subscription {0}").format(
                    self.subscription
                )
            )
            return

        company = self.company or frappe.db.get_single_value(
            "Non Profit Settings", "company"
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        sub = frappe.new_doc("Subscription")
        sub.update(
            {
                "party_type": "Customer",
                "party": self.customer,
                "company": company,
                "start_date": self.member_since_date,
                "generate_invoice_at": "Beginning of the current subscription period",
                "submit_invoice": 1,
                "follow_calendar_months": 0,
                "cost_center": cost_center,
                "plans": [{"plan": subscription_plan, "qty": 1}],
            }
        )
        sub.insert()

        try:
            invoice = sub.create_invoice()
            frappe.msgprint(
                _("Subscription {0} created with invoice {1}").format(sub.name, invoice)
            )
        except Exception as e:
            frappe.msgprint(
                _("Subscription {0} created. Invoice generation pending.").format(
                    sub.name
                )
            )
            frappe.log_error(str(e), "Subscription Invoice Creation")

        self.db_set("subscription", sub.name)

    def cancel_subscription(self):
        """Cancel the associated subscription when membership is cancelled."""
        if not self.subscription:
            return

        try:
            sub = frappe.get_doc("Subscription", self.subscription)
            if sub.status not in ["Cancelled", "Completed"]:
                sub.cancel_subscription()
                frappe.msgprint(_("Subscription {0} cancelled").format(sub.name))
        except Exception as e:
            frappe.log_error(
                str(e), f"Error cancelling subscription {self.subscription}"
            )

    def sync_status_from_subscription(self):
        """Update subscription_status field from linked subscription."""
        if self.subscription:
            status = frappe.db.get_value("Subscription", self.subscription, "status")
            if status and status != self.subscription_status:
                self.subscription_status = status
                self.db_set("subscription_status", status)

    def get_status_display(self):
        """Return human-readable status based on subscription."""
        status = self.subscription_status

        status_map = {
            "Active": "Current",
            "Trialing": "New",
            "Grace Period": "Pending",
            "Cancelled": "Cancelled",
            "Unpaid": "Expired",
            "Completed": "Expired",
        }

        return status_map.get(status, "Current" if status else "New")


def get_membership_status(member):
    """Get the current membership status for a member."""
    membership = frappe.db.get_value(
        "Membership",
        {"member": member, "docstatus": 1},
        ["name", "subscription"],
        as_dict=True,
        order_by="creation DESC",
    )

    if not membership:
        return None

    if membership.subscription:
        return frappe.db.get_value("Subscription", membership.subscription, "status")

    return "Active"
