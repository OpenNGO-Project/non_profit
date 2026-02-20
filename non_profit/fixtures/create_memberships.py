"""Create missing memberships for existing members and fix role permissions."""

import frappe
from frappe.utils import getdate


def execute():
    print("Creating membership type and memberships...")

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


def get_or_create_membership_type():
    membership_type = frappe.db.exists("Membership Type", "ÖDP Mitglied")
    if membership_type:
        print(f"  Membership type exists: {membership_type}")
        return membership_type

    item = get_or_create_membership_item()

    doc = frappe.new_doc("Membership Type")
    doc.membership_type = "ÖDP Mitglied"
    doc.amount = 60
    doc.linked_item = item.name
    doc.auto_create_subscription_plan = 1
    doc.insert()
    frappe.db.commit()
    print(f"  Created membership type: {doc.name}")
    return doc.name


def get_or_create_membership_item():
    item_code = "ÖDP Mitgliedschaft"
    existing = frappe.db.exists("Item", item_code)
    if existing:
        return frappe.get_doc("Item", existing)

    item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
    if not item_group:
        item_group = "Products"

    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = "ÖDP Mitgliedschaft"
    item.item_group = item_group
    item.stock_uom = "nos"
    item.is_stock_item = 0
    item.is_sales_item = 1
    item.insert()
    frappe.db.commit()
    print(f"  Created item: {item.name}")
    return item


def get_default_company():
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        if companies:
            company = companies[0].name
    return company
