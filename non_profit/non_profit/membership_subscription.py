from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate


DEFAULT_GENERATE_INVOICE_AT = "End of the current subscription period"


def ensure_membership_subscription_plan(
	membership_type: str,
	*,
	plan_name: str | None = None,
	item: str | None = None,
	currency: str | None = None,
	cost: float | None = None,
	billing_interval: str = "Year",
	billing_interval_count: int = 1,
) -> str | None:
	"""Create or update an ERPNext Subscription Plan for a Membership Type."""
	if not frappe.db.exists("DocType", "Subscription Plan"):
		return None

	membership_type_doc = frappe.get_doc("Membership Type", membership_type)
	plan_name = plan_name or f"{membership_type_doc.name} Subscription"
	item = item or membership_type_doc.get("linked_item")
	if not item:
		frappe.throw(_("Please set a Linked Item for Membership Type {0}.").format(membership_type_doc.name))

	currency = currency or frappe.db.get_default("currency") or "CHF"
	cost = flt(cost if cost is not None else membership_type_doc.get("amount"))
	values = {
		"item": item,
		"price_determination": "Fixed Rate",
		"cost": cost,
		"billing_interval": billing_interval,
		"billing_interval_count": billing_interval_count,
		"currency": currency,
	}

	if frappe.db.exists("Subscription Plan", plan_name):
		current = frappe.db.get_value("Subscription Plan", plan_name, list(values), as_dict=True)
		updates = {key: value for key, value in values.items() if current.get(key) != value}
		if updates:
			frappe.db.set_value("Subscription Plan", plan_name, updates, update_modified=False)
		return plan_name

	plan = frappe.get_doc(
		{
			"doctype": "Subscription Plan",
			"plan_name": plan_name,
			**values,
		}
	)
	plan.insert(ignore_permissions=True)
	return plan.name


def ensure_membership_subscription(
	membership,
	*,
	member=None,
	customer: str | None = None,
	plan_name: str | None = None,
	item: str | None = None,
	currency: str | None = None,
	cost: float | None = None,
	company: str | None = None,
	start_date=None,
	end_date=None,
	generate_invoice_at: str = DEFAULT_GENERATE_INVOICE_AT,
	days_until_due: int = 30,
	submit_invoice: int = 1,
	clear_membership_to_date: bool = True,
) -> str | None:
	"""Create and link an ERPNext Subscription for a Membership.

	The helper is intentionally generic: client apps decide the plan name and
	billing defaults, while non_profit owns the Membership -> Subscription
	linking contract.
	"""
	if not frappe.db.exists("DocType", "Subscription"):
		return None

	if isinstance(membership, str):
		membership = frappe.get_doc("Membership", membership)
	if membership.get("subscription") and frappe.db.exists("Subscription", membership.subscription):
		if clear_membership_to_date:
			_clear_membership_to_date(membership)
		return membership.subscription

	if member is None:
		member = frappe.get_doc("Member", membership.member)
	elif isinstance(member, str):
		member = frappe.get_doc("Member", member)

	customer = customer or member.get("customer") or membership.get("customer")
	if not customer:
		frappe.throw(_("A Customer is required before creating a Membership Subscription."))

	plan = ensure_membership_subscription_plan(
		membership.membership_type,
		plan_name=plan_name,
		item=item,
		currency=currency or membership.get("currency"),
		cost=cost if cost is not None else membership.get("amount"),
	)
	if not plan:
		return None

	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"party_type": "Customer",
			"party": customer,
			"company": company or membership.get("company"),
			"start_date": start_date or membership.get("from_date") or nowdate(),
			"end_date": end_date,
			"generate_invoice_at": generate_invoice_at,
			"days_until_due": days_until_due,
			"submit_invoice": submit_invoice,
			"plans": [{"plan": plan, "qty": 1}],
		}
	)
	subscription.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Membership",
		membership.name,
		"subscription",
		subscription.name,
		update_modified=False,
	)
	membership.subscription = subscription.name
	if clear_membership_to_date:
		_clear_membership_to_date(membership)
	return subscription.name


def _clear_membership_to_date(membership) -> None:
	if membership.get("to_date"):
		frappe.db.set_value("Membership", membership.name, "to_date", None, update_modified=False)
		membership.to_date = None
