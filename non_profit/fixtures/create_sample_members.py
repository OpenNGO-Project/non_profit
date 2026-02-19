"""
Create sample members and test users for ÖDP membership system.

This script creates:
- 35 members (one per chapter)
- 35 customers linked to members
- 35 addresses linked to customers
- 35 memberships (submitted, with subscriptions)
- 7 test users with chapter permissions for testing

Run: bench --site <site> execute non_profit.fixtures.create_sample_members.execute
"""

import frappe
from frappe import _
from frappe.utils import getdate


def execute():
    """Main function to create all sample data."""
    print("Creating sample data for ÖDP membership system...")

    create_sample_members()
    create_test_users()

    print("\nSample data creation complete!")
    print_summary()


def create_sample_members():
    """Create 35 sample members, one per chapter."""
    print("\n=== Creating Sample Members ===")

    chapters = frappe.get_all(
        "Chapter", fields=["name", "chapter_type", "region"], order_by="lft"
    )

    company = get_default_company()
    membership_type = "ÖDP Mitglied"

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

    # Clean chapter name for email (replace special chars)
    chapter_slug = chapter.name.lower()
    chapter_slug = chapter_slug.replace(" ", ".").replace("-", ".")
    chapter_slug = chapter_slug.replace("(", "").replace(")", "")
    # Replace German umlauts
    chapter_slug = chapter_slug.replace("ö", "oe").replace("ü", "ue").replace("ä", "ae")
    chapter_slug = chapter_slug.replace("ß", "ss").replace(".", ".")
    # Remove any remaining non-ASCII chars
    chapter_slug = "".join(c for c in chapter_slug if ord(c) < 128 or c == ".")
    # Clean up multiple dots
    while ".." in chapter_slug:
        chapter_slug = chapter_slug.replace("..", ".")

    email = f"mitglied.{chapter_slug}@oedp-test.de"

    # Check if member already exists
    existing = frappe.db.exists("Member", {"email_id": email})
    if existing:
        return None

    member_name = f"Mitglied {chapter.name}"

    # Create Member
    member = frappe.new_doc("Member")
    member.update(
        {
            "member_name": member_name,
            "email_id": email,
            "membership_type": membership_type,
            "primary_chapter": chapter.name,
        }
    )
    member.insert()

    # Create Customer
    customer = create_customer_for_member(member)

    # Create Address
    create_address_for_customer(customer, member_name, index)

    # Create Membership
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


def create_customer_for_member(member):
    """Create a customer linked to a member."""
    customer = frappe.new_doc("Customer")
    customer.update(
        {
            "customer_name": member.member_name,
            "customer_type": "Individual",
            "customer_group": get_customer_group(),
            "territory": get_territory(),
        }
    )
    customer.flags.ignore_mandatory = True
    customer.insert()

    # Link customer to member
    member.db_set("customer", customer.name)

    return customer


def create_address_for_customer(customer, member_name, index):
    """Create an address for a customer."""
    address = frappe.new_doc("Address")
    address.update(
        {
            "address_title": member_name,
            "address_type": "Billing",
            "address_line1": f"Hauptstraße {index}",
            "city": "Berlin",
            "pincode": "10115",
            "country": "Germany",
        }
    )
    address.insert()

    # Link address to customer
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
    """Create 7 test users with chapter permissions."""
    print("\n=== Creating Test Users ===")

    test_users = [
        {
            "email": "test-admin@oedp-test.de",
            "name": "Test Admin",
            "chapter": None,
            "role": "Non Profit Manager",
            "description": "Can see all members (manager role)",
        },
        {
            "email": "test-bundesverband@oedp-test.de",
            "name": "Test Bundesverband",
            "chapter": "Bundesverband",
            "access_level": "Full Access",
            "description": "Can see all members (top level)",
        },
        {
            "email": "test-bayern@oedp-test.de",
            "name": "Test Bayern",
            "chapter": "Landesverband Bayern",
            "access_level": "Full Access",
            "description": "Can see Bavaria members",
        },
        {
            "email": "test-oberbayern@oedp-test.de",
            "name": "Test Oberbayern",
            "chapter": "Bezirksverband Oberbayern",
            "access_level": "Full Access",
            "description": "Can see Oberbayern members",
        },
        {
            "email": "test-muenchen-land@oedp-test.de",
            "name": "Test München-Land",
            "chapter": "Kreisverband München-Land",
            "access_level": "Full Access",
            "description": "Can see München-Land members",
        },
        {
            "email": "test-pullach@oedp-test.de",
            "name": "Test Pullach",
            "chapter": "Ortsverband Pullach",
            "access_level": "Full Access",
            "description": "Can see only Pullach member",
        },
        {
            "email": "test-thueringen@oedp-test.de",
            "name": "Test Thüringen",
            "chapter": "Landesverband Thüringen",
            "access_level": "Full Access",
            "description": "Can see Thuringia members",
        },
    ]

    password = "OedpTest123!"

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

    # Check if user exists
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

    # Add role
    if user_data.get("role"):
        if not frappe.db.exists(
            "Has Role", {"parent": user.name, "role": user_data["role"]}
        ):
            user.add_roles(user_data["role"])
    else:
        # Default role for chapter users
        if not frappe.db.exists(
            "Has Role", {"parent": user.name, "role": "Non Profit Member"}
        ):
            user.add_roles("Non Profit Member")

    # Create chapter permission
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


def get_default_company():
    """Get default company from settings or first company."""
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        if companies:
            company = companies[0].name
    return company


def get_customer_group():
    """Get or create customer group for members."""
    group = frappe.db.exists("Customer Group", "Members")
    if group:
        return group

    root = frappe.db.get_value("Customer Group", {"is_group": 1}, "name")

    customer_group = frappe.new_doc("Customer Group")
    customer_group.update(
        {
            "customer_group_name": "Members",
            "parent_customer_group": root or "All Customer Groups",
        }
    )
    customer_group.insert()

    return customer_group.name


def get_territory():
    """Get default territory."""
    territory = frappe.db.get_value("Territory", {"is_group": 1}, "name")
    return territory or "All Territories"


def print_summary():
    """Print summary of created data."""
    print("\n=== Summary ===")

    members = frappe.db.count("Member")
    memberships = frappe.db.count("Membership", {"docstatus": 1})
    customers = frappe.db.count("Customer")
    subscriptions = frappe.db.count("Subscription")
    invoices = frappe.db.count("Sales Invoice")

    print(f"Total Members: {members}")
    print(f"Submitted Memberships: {memberships}")
    print(f"Customers: {customers}")
    print(f"Subscriptions: {subscriptions}")
    print(f"Sales Invoices: {invoices}")

    print("\n=== Test Users ===")
    print("Email                          | Role                | Chapter")
    print("-" * 80)

    test_emails = [
        "test-admin@oedp-test.de",
        "test-bundesverband@oedp-test.de",
        "test-bayern@oedp-test.de",
        "test-oberbayern@oedp-test.de",
        "test-muenchen-land@oedp-test.de",
        "test-pullach@oedp-test.de",
        "test-thueringen@oedp-test.de",
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

            print(f"{email:30} | {role:19} | {chapter}")

    print(f"\nAll test users password: OedpTest123!")


def verify_permissions():
    """Verify that permissions work correctly for test users."""
    print("\n=== Verifying Permissions ===")

    test_cases = [
        ("test-bundesverband@oedp-test.de", 35, "Should see all 35 members"),
        ("test-bayern@oedp-test.de", 26, "Should see Bavaria members (~26)"),
        ("test-pullach@oedp-test.de", 1, "Should see only 1 member (Pullach)"),
    ]

    for email, expected_count, description in test_cases:
        frappe.set_user(email)
        visible = frappe.get_all("Member", fields=["name"])
        count = len(visible)
        status = "✓" if count >= expected_count else "✗"
        print(f"  {status} {email}: {count} members ({description})")

    frappe.set_user("Administrator")
