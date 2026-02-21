"""
Create sample members and test users for membership system.

This script creates:
- Members (one per chapter)
- Customers linked to members
- Addresses linked to customers
- Memberships (submitted, with subscriptions)
- Test users with chapter permissions

Run: bench --site <site> execute non_profit.fixtures.create_sample_members.execute
"""

import frappe
from frappe import _
from frappe.utils import getdate

from non_profit.non_profit.utils import (
    get_customer_group,
    get_default_company,
    get_default_membership_type,
    get_territory,
)


def execute():
    """Main function to create all sample data."""
    print("Creating sample data for membership system...")

    create_sample_members()
    create_test_users()

    print("\nSample data creation complete!")
    print_summary()


def create_sample_members():
    """Create sample members, one per chapter."""
    print("\n=== Creating Sample Members ===")

    chapters = frappe.get_all(
        "Chapter", fields=["name", "chapter_type", "region"], order_by="lft"
    )

    company = get_default_company()
    membership_type = get_default_membership_type()

    created = 0
    for idx, chapter in enumerate(chapters, 1):
        try:
            member = create_member_for_chapter(chapter, idx, company, membership_type)
            if member:
                created += 1
                print(
                    f"  [{created}/{len(chapters)}] Created member for: {chapter.name}"
                )
        except Exception as e:
            print(f"  Error creating member for {chapter.name}: {str(e)}")

    print(f"\nCreated {created} members with memberships")


def create_member_for_chapter(chapter, index, company, membership_type):
    """Create a member, customer, address, and membership for a chapter."""

    slug = make_slug(chapter.name)
    email = f"member.{slug}@example.com"

    if frappe.db.exists("Member", {"email_id": email}):
        return None

    member_name = f"Member {chapter.name}"

    customer = create_customer_for_member_name(member_name)

    member = frappe.new_doc("Member")
    member.update(
        {
            "member_name": member_name,
            "email_id": email,
            "primary_chapter": chapter.name,
            "customer": customer.name,
        }
    )
    member.insert()

    create_address_for_customer(customer, member_name, index)

    if membership_type:
        membership = frappe.new_doc("Membership")
        membership.update(
            {
                "member": member.name,
                "membership_type": membership_type,
                "company": company,
                "member_since_date": getdate(),
                "auto_renew": 1,
            }
        )
        membership.insert()
        membership.submit()

    return member


def make_slug(name):
    """Convert a name to a URL-safe slug."""
    slug = name.lower()
    slug = slug.replace(" ", ".").replace("-", ".")
    slug = slug.replace("(", "").replace(")", "")
    slug = "".join(c for c in slug if c.isalnum() or c == ".")
    while ".." in slug:
        slug = slug.replace("..", ".")
    return slug


def create_customer_for_member_name(member_name):
    """Create a customer for a member."""
    customer = frappe.new_doc("Customer")
    customer.update(
        {
            "customer_name": member_name,
            "customer_type": "Individual",
            "customer_group": get_customer_group(),
            "territory": get_territory(),
        }
    )
    customer.flags.ignore_mandatory = True
    customer.insert()

    return customer


def create_address_for_customer(customer, member_name, index):
    """Create an address for a customer."""
    address = frappe.new_doc("Address")
    address.update(
        {
            "address_title": member_name,
            "address_type": "Billing",
            "address_line1": f"Main Street {index}",
            "city": "City",
            "pincode": "10000",
            "country": "Country",
        }
    )
    address.insert()

    address.append(
        "links",
        {
            "link_doctype": "Customer",
            "link_name": customer.name,
        },
    )
    address.save()

    return address


def create_test_users():
    """Create test users with chapter permissions."""
    print("\n=== Creating Test Users ===")

    chapters = frappe.get_all("Chapter", fields=["name"], order_by="lft", limit=6)

    test_users = [
        {
            "email": "admin@example.com",
            "name": "Test Admin",
            "chapter": None,
            "role": "Non Profit Manager",
            "description": "Can see all members (manager role)",
        },
    ]

    if chapters:
        test_users.append(
            {
                "email": "top-level@example.com",
                "name": "Test Top Level",
                "chapter": chapters[0].name,
                "access_level": "Full Access",
                "description": f"Can see all members (top level: {chapters[0].name})",
            }
        )

        if len(chapters) > 2:
            test_users.append(
                {
                    "email": "mid-level@example.com",
                    "name": "Test Mid Level",
                    "chapter": chapters[1].name,
                    "access_level": "Full Access",
                    "description": f"Can see {chapters[1].name} members",
                }
            )

        if len(chapters) > 5:
            test_users.append(
                {
                    "email": "low-level@example.com",
                    "name": "Test Low Level",
                    "chapter": chapters[-1].name,
                    "access_level": "Full Access",
                    "description": f"Can see only {chapters[-1].name}",
                }
            )

    password = "Test123456!"

    created = 0
    for user_data in test_users:
        try:
            user = create_test_user(user_data, password)
            if user:
                created += 1
                print(f"  Created: {user_data['email']} - {user_data['description']}")
        except Exception as e:
            print(f"  Error creating user {user_data['email']}: {str(e)}")

    print(f"\nCreated {created} test users")
    print(f"All test users have password: {password}")


def create_test_user(user_data, password):
    """Create a test user with chapter permissions."""

    existing = frappe.db.exists("User", user_data["email"])
    if existing:
        user = frappe.get_doc("User", existing)
    else:
        user = frappe.new_doc("User")
        user.update(
            {
                "email": user_data["email"],
                "first_name": user_data["name"],
                "send_welcome_email": 0,
                "new_password": password,
            }
        )
        user.insert()

    if user_data.get("role"):
        if not frappe.db.exists(
            "Has Role", {"parent": user.name, "role": user_data["role"]}
        ):
            user.add_roles(user_data["role"])
    else:
        if not frappe.db.exists(
            "Has Role", {"parent": user.name, "role": "Non Profit Member"}
        ):
            user.add_roles("Non Profit Member")

    if user_data.get("chapter"):
        existing_perm = frappe.db.exists(
            "User Permission",
            {"user": user.name, "allow": "Chapter", "for_value": user_data["chapter"]},
        )

        if not existing_perm:
            perm = frappe.new_doc("User Permission")
            perm.update(
                {
                    "user": user.name,
                    "allow": "Chapter",
                    "for_value": user_data["chapter"],
                    "access_level": user_data.get("access_level", "Full Access"),
                }
            )
            perm.insert()

    return user


def print_summary():
    """Print summary of created data."""
    print("\n=== Summary ===")

    members = frappe.db.count("Member")
    memberships = frappe.db.count("Membership", {"docstatus": 1})
    customers = frappe.db.count("Customer")
    subscriptions = frappe.db.count("Subscription")

    print(f"Total Members: {members}")
    print(f"Submitted Memberships: {memberships}")
    print(f"Customers: {customers}")
    print(f"Subscriptions: {subscriptions}")

    print("\n=== Test Users ===")
    print("Email                    | Role                | Chapter")
    print("-" * 60)

    test_emails = [
        "admin@example.com",
        "top-level@example.com",
        "mid-level@example.com",
        "low-level@example.com",
    ]

    for email in test_emails:
        user = frappe.db.get_value("User", email, ["first_name"], as_dict=True)
        if user:
            roles = frappe.get_all(
                "Has Role", filters={"parent": email}, fields=["role"]
            )
            role = roles[0].role if roles else "No role"

            perm = frappe.db.get_value(
                "User Permission",
                {"user": email, "allow": "Chapter"},
                "for_value",
                as_dict=True,
            )
            chapter = perm.for_value if perm else "All (manager)"

            print(f"{email:24} | {role:19} | {chapter}")

    print(f"\nAll test users password: Test123456!")
