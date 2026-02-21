"""Create missing memberships for existing members and fix role permissions."""

import frappe
from frappe.utils import getdate

from non_profit.non_profit.utils import (
    get_default_company,
    get_or_create_membership_type,
)


def execute():
    print("Creating memberships...")

    membership_type = get_or_create_membership_type()

    company = get_default_company()
    members = frappe.get_all("Member", fields=["name", "customer"])

    created = 0
    for member in members:
        existing_membership = frappe.db.exists("Membership", {"member": member.name})
        if existing_membership:
            continue

        if not member.customer:
            print(f"  Skipping {member.name}: no customer")
            continue

        try:
            membership = frappe.new_doc("Membership")
            membership.member = member.name
            membership.membership_type = membership_type
            membership.company = company
            membership.member_since_date = getdate()
            membership.auto_renew = 1
            membership.insert()
            membership.submit()
            created += 1
            print(f"  Created membership for: {member.name}")
        except Exception as e:
            print(f"  Error for {member.name}: {str(e)}")

    frappe.db.commit()
    print(f"\nCreated {created} memberships")

    add_role_permissions()


def add_role_permissions():
    """Add Non Profit Member role to Subscription and Sales Invoice."""
    print("\nAdding role permissions...")

    doctypes = [
        ("Subscription", {"read": 1, "write": 0, "create": 0, "delete": 0}),
        ("Sales Invoice", {"read": 1, "write": 0, "create": 0, "delete": 0}),
    ]

    for doctype, perms in doctypes:
        add_permission_for_role(doctype, "Non Profit Member", perms)


def add_permission_for_role(doctype, role, perms):
    """Add or update permission for a role on a doctype."""
    existing = frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role})

    if existing:
        print(f"  Permission already exists: {role} on {doctype}")
        return

    try:
        perm_doc = frappe.get_doc(
            {
                "doctype": "Custom DocPerm",
                "parent": doctype,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role,
                "permlevel": 0,
                **perms,
            }
        )
        perm_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"  Added permission: {role} on {doctype}")
    except Exception as e:
        print(f"  Error adding permission for {doctype}: {str(e)}")
