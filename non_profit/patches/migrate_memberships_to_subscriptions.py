"""
Migrate existing Memberships to create Subscriptions.

This script:
1. Creates Subscription Plans for Membership Types that don't have one
2. Creates Subscriptions for active Memberships with auto_renew enabled

Run: bench --site <site> execute non_profit.patches.migrate_memberships_to_subscriptions.execute
"""

import frappe
from frappe import _


def execute():
    """Main migration function."""
    print("Starting membership subscription migration...")

    create_subscription_plans_for_membership_types()
    create_subscriptions_for_active_memberships()

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


def create_subscriptions_for_active_memberships():
    """Create Subscriptions for active Memberships."""
    print("\nCreating Subscriptions for active Memberships...")

    active_memberships = frappe.db.sql(
        """
        SELECT m.name, m.member, m.membership_type, m.from_date, m.to_date, m.company
        FROM `tabMembership` m
        WHERE m.membership_status IN ('Current', 'New')
        AND m.docstatus = 1
        AND m.subscription IS NULL
        ORDER BY m.to_date DESC
    """,
        as_dict=True,
    )

    processed_members = set()
    created = 0
    skipped = 0

    for m in active_memberships:
        if m.member in processed_members:
            continue

        processed_members.add(m.member)

        try:
            subscription_name = create_subscription_for_membership(m)
            if subscription_name:
                created += 1
                print(
                    f"  Created subscription for member {m.member}: {subscription_name}"
                )
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
            print(f"  Error for member {m.member}: {str(e)}")

    frappe.db.commit()
    print(f"\nSubscriptions: {created} created, {skipped} skipped")


def create_subscription_for_membership(membership_data):
    """Create a Subscription for a membership."""
    member = frappe.get_doc("Member", membership_data.member)

    if not member.customer:
        if hasattr(member, "create_customer"):
            member.create_customer()
            member.reload()
        else:
            customer = create_customer_for_member(member)
            member.db_set("customer", customer)
            member.reload()

    if not member.customer:
        print(f"    Cannot create subscription: No customer for member {member.name}")
        return None

    subscription_plan = frappe.db.get_value(
        "Membership Type", membership_data.membership_type, "subscription_plan"
    )

    if not subscription_plan:
        print(
            f"    Cannot create subscription: No Subscription Plan for {membership_data.membership_type}"
        )
        return None

    company = membership_data.company or frappe.db.get_single_value(
        "Non Profit Settings", "company"
    )
    cost_center = frappe.db.get_value("Company", company, "cost_center")

    sub = frappe.new_doc("Subscription")
    sub.update(
        {
            "party_type": "Customer",
            "party": member.customer,
            "company": company,
            "start_date": membership_data.from_date,
            "generate_invoice_at": "Beginning of the current subscription period",
            "submit_invoice": 1,
            "follow_calendar_months": 1,
            "cost_center": cost_center,
            "plans": [{"plan": subscription_plan, "qty": 1}],
        }
    )
    sub.insert()

    member.db_set("subscription", sub.name)
    frappe.db.set_value("Membership", membership_data.name, "subscription", sub.name)

    return sub.name


def create_customer_for_member(member):
    """Create a Customer for a Member."""
    customer = frappe.new_doc("Customer")
    customer.update(
        {
            "customer_name": member.member_name,
            "customer_type": "Individual",
            "customer_group": get_customer_group(),
            "territory": get_territory(),
        }
    )

    if member.email_id:
        customer.append("contact_info", {"email_id": member.email_id})

    customer.insert()
    return customer.name


def get_customer_group():
    """Get or create Customer Group for members."""
    group = frappe.db.exists("Customer Group", "Members")
    if group:
        return group

    root_group = frappe.db.get_value(
        "Customer Group", {"parent_customer_group": ""}, "name"
    )

    customer_group = frappe.new_doc("Customer Group")
    customer_group.update(
        {
            "customer_group_name": "Members",
            "parent_customer_group": root_group or "All Customer Groups",
        }
    )
    customer_group.insert()
    return customer_group.name


def get_territory():
    """Get default territory."""
    territory = frappe.db.get_value("Territory", {"is_group": 1}, "name")
    return territory or "All Territories"


def get_company_currency():
    """Get default company currency."""
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if company:
        return frappe.db.get_value("Company", company, "default_currency") or "EUR"
    return "EUR"
