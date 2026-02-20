"""
Hooks for integrating Membership with ERPNext Subscription.

Simplified for indefinite memberships:
- Membership is created once and persists
- Subscription generates invoices yearly
- No new membership records created on renewal
"""

import frappe
from frappe import _


def sync_membership_status_from_subscription(subscription, method):
    """
    Update linked Membership status when Subscription status changes.

    Called via doc_events on Subscription.
    """
    memberships = frappe.db.sql_list(
        "SELECT name FROM `tabMembership` WHERE subscription = %s AND docstatus = 1",
        subscription.name,
    )

    for membership_name in memberships:
        frappe.db.set_value(
            "Membership", membership_name, "subscription_status", subscription.status
        )


def ensure_subscriptions_for_members():
    """
    Scheduled task to ensure active members have subscriptions.

    Checks for memberships with auto_renew enabled but no subscription.
    """
    memberships_without_subscription = frappe.db.sql(
        """
        SELECT m.name, m.member, m.membership_type, m.member_since_date
        FROM `tabMembership` m
        WHERE m.auto_renew = 1
        AND m.docstatus = 1
        AND m.subscription IS NULL
    """,
        as_dict=True,
    )

    for m in memberships_without_subscription:
        try:
            membership = frappe.get_doc("Membership", m.name)
            membership.create_subscription()
            print(f"Created subscription for membership {membership.name}")
        except Exception as e:
            frappe.log_error(
                f"Error creating subscription for membership {m.name}: {str(e)}",
                "Membership Subscription Error",
            )


def cancel_membership_on_subscription_cancel(subscription, method):
    """
    Cancel the Membership when its Subscription is cancelled.

    Called via doc_events on Subscription cancellation.
    """
    if subscription.party_type != "Customer":
        return

    membership = frappe.db.get_value(
        "Membership",
        {"subscription": subscription.name, "docstatus": 1},
        "name",
    )

    if membership:
        try:
            mem_doc = frappe.get_doc("Membership", membership)
            mem_doc.cancel()
            frappe.msgprint(_("Membership {0} cancelled").format(membership))
        except Exception as e:
            frappe.log_error(
                f"Error cancelling membership {membership}: {str(e)}",
                "Membership Subscription Error",
            )
