import frappe
from frappe import _
from frappe.model.document import Document


class MembershipType(Document):
    def validate(self):
        if self.linked_item:
            is_stock_item = frappe.db.get_value(
                "Item", self.linked_item, "is_stock_item"
            )
            if is_stock_item:
                frappe.throw(_("The Linked Item should be a service item"))

    def on_update(self):
        if self.auto_create_subscription_plan and self.linked_item:
            self.create_or_update_subscription_plan()

    def create_or_update_subscription_plan(self):
        plan_name = f"Membership - {self.membership_type}"

        if frappe.db.exists("Subscription Plan", plan_name):
            plan = frappe.get_doc("Subscription Plan", plan_name)
        else:
            plan = frappe.new_doc("Subscription Plan")
            plan.plan_name = plan_name

        currency = self.get_company_currency()

        plan.update(
            {
                "item": self.linked_item,
                "cost": self.amount,
                "currency": currency,
                "billing_interval": "Year",
                "billing_interval_count": 1,
                "price_determination": "Fixed Rate",
            }
        )
        plan.save()

        self.db_set("subscription_plan", plan.name)

        frappe.msgprint(_("Subscription Plan {0} created/updated").format(plan.name))

    def get_company_currency(self):
        company = frappe.db.get_single_value("Non Profit Settings", "company")
        if company:
            return frappe.db.get_value("Company", company, "default_currency") or "EUR"
        return "EUR"


def get_membership_type(razorpay_id):
    return frappe.db.exists("Membership Type", {"razorpay_plan_id": razorpay_id})
