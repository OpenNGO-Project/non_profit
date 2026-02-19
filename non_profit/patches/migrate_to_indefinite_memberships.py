"""
Migrate existing yearly Memberships to indefinite Memberships.

This script:
1. Creates Subscription Plans for Membership Types
2. Merges multiple yearly memberships into single indefinite records
3. Creates Subscriptions for active memberships

Run: bench --site <site> execute non_profit.patches.migrate_to_indefinite_memberships.execute
"""

import frappe
from frappe import _


def execute():
    """Main migration function."""
    print("Starting migration to indefinite memberships...")

    create_subscription_plans_for_membership_types()
    merge_yearly_memberships()

    print("Migration complete!")


def create_subscription_plans_for_membership_types():
    """Create Subscription Plans for all Membership Types."""
    print("\nCreating Subscription Plans for Membership Types...")

    membership_types = frappe.get_all(
        "Membership Type",
        fields=["name", "membership_type", "amount", "linked_item"],
        filters={"linked_item": ["!=", ""]},
    )

    for mt in membership_types:
        existing_plan = frappe.db.exists(
            "Subscription Plan", {"plan_name": f"Membership - {mt.membership_type}"}
        )

        if existing_plan:
            print(f"  Skipping {mt.membership_type}: Subscription Plan already exists")
            continue

        if not mt.linked_item:
            print(f"  Skipping {mt.membership_type}: No linked item")
            continue

        currency = get_company_currency()

        plan = frappe.new_doc("Subscription Plan")
        plan.update(
            {
                "plan_name": f"Membership - {mt.membership_type}",
                "item": mt.linked_item,
                "cost": mt.amount,
                "currency": currency,
                "billing_interval": "Year",
                "billing_interval_count": 1,
                "price_determination": "Fixed Rate",
            }
        )
        plan.insert()

        frappe.db.set_value("Membership Type", mt.name, "subscription_plan", plan.name)
        print(f"  Created Subscription Plan for {mt.membership_type}: {plan.name}")

    frappe.db.commit()


def merge_yearly_memberships():
    """Merge multiple yearly memberships into single indefinite records."""
    print("\nMerging yearly memberships...")

    members_with_multiple_memberships = frappe.db.sql(
        """
        SELECT member, COUNT(*) as count
        FROM `tabMembership`
        WHERE docstatus < 2
        GROUP BY member
        ORDER BY count DESC
    """,
        as_dict=True,
    )

    merged = 0
    kept = 0

    for m in members_with_multiple_memberships:
        memberships = frappe.get_all(
            "Membership",
            filters={"member": m.member, "docstatus": ["<", 2]},
            fields=["name", "from_date", "to_date", "subscription", "docstatus"],
            order_by="from_date ASC",
        )

        if len(memberships) <= 1:
            kept += 1
            continue

        primary = memberships[0]
        primary_doc = frappe.get_doc("Membership", primary.name)

        earliest_date = min(get_date(m.from_date) for m in memberships if m.from_date)

        primary_doc.member_since_date = earliest_date
        primary_doc.auto_renew = 1

        if primary_doc.docstatus == 1:
            primary_doc.save()
        else:
            primary_doc.save()

        for other in memberships[1:]:
            try:
                other_doc = frappe.get_doc("Membership", other.name)
                if other_doc.docstatus == 1:
                    other_doc.cancel()
                other_doc.delete()
                merged += 1
            except Exception as e:
                print(f"  Error merging {other.name}: {str(e)}")

        print(f"  Merged {len(memberships)} memberships for member {m.member}")

    frappe.db.commit()
    print(f"\nMerged {merged} memberships, kept {kept} single memberships")


def get_date(date_str):
    """Convert date string to date object."""
    from frappe.utils import getdate

    return getdate(date_str) if date_str else None


def get_company_currency():
    """Get default company currency."""
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if company:
        return frappe.db.get_value("Company", company, "default_currency") or "EUR"
    return "EUR"
