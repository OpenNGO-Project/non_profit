"""
Generic Demo Data Setup

This script creates generic chapter types and a sample hierarchy structure
that can be used for testing and development.

Run: bench --site <site> execute non_profit.fixtures.setup_demo.setup_demo_structure
"""

import frappe


def setup_demo_structure():
    """Main function to set up generic demo structure."""
    print("Setting up demo structure...")

    create_chapter_types()
    create_sample_hierarchy()

    print("Demo structure setup complete!")


def create_chapter_types():
    """Create generic Chapter Types for organizational hierarchy."""
    print("Creating Chapter Types...")

    chapter_types = [
        {
            "name": "National",
            "level": 0,
            "sort_order": 0,
            "description": "National level organization",
        },
        {
            "name": "Regional",
            "level": 1,
            "sort_order": 10,
            "description": "Regional level (state/province)",
        },
        {
            "name": "District",
            "level": 2,
            "sort_order": 20,
            "description": "District level",
        },
        {"name": "Local", "level": 3, "sort_order": 30, "description": "Local chapter"},
        {
            "name": "Committee",
            "level": 1,
            "sort_order": 50,
            "description": "Working group or committee",
        },
    ]

    for ct in chapter_types:
        if not frappe.db.exists("Chapter Type", ct["name"]):
            doc = frappe.get_doc({"doctype": "Chapter Type", **ct})
            doc.insert()
            print(f"  Created: {ct['name']}")
        else:
            print(f"  Exists: {ct['name']}")

    frappe.db.commit()


def create_sample_hierarchy():
    """Create sample chapter hierarchy."""
    print("Creating chapter hierarchy...")

    chapters = get_demo_chapters()

    for chapter_data in chapters:
        create_chapter(chapter_data)

    frappe.db.commit()
    print(f"Created/updated {len(chapters)} chapters")


def get_demo_chapters():
    """Return list of generic demo chapter data."""
    return [
        {
            "name": "National Chapter",
            "chapter_type": "National",
            "region": "National",
            "parent_chapter": None,
            "published": 1,
            "introduction": "National level organization",
        },
        {
            "name": "Region North",
            "chapter_type": "Regional",
            "region": "North",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Northern region",
        },
        {
            "name": "Region South",
            "chapter_type": "Regional",
            "region": "South",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Southern region",
        },
        {
            "name": "Region East",
            "chapter_type": "Regional",
            "region": "East",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Eastern region",
        },
        {
            "name": "Region West",
            "chapter_type": "Regional",
            "region": "West",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Western region",
        },
        {
            "name": "District A",
            "chapter_type": "District",
            "region": "North-A",
            "parent_chapter": "Region North",
            "published": 1,
            "introduction": "District A in North",
        },
        {
            "name": "District B",
            "chapter_type": "District",
            "region": "North-B",
            "parent_chapter": "Region North",
            "published": 1,
            "introduction": "District B in North",
        },
        {
            "name": "District C",
            "chapter_type": "District",
            "region": "South-A",
            "parent_chapter": "Region South",
            "published": 1,
            "introduction": "District C in South",
        },
        {
            "name": "Local Chapter 1",
            "chapter_type": "Local",
            "region": "North-A-1",
            "parent_chapter": "District A",
            "published": 1,
            "introduction": "Local chapter 1",
        },
        {
            "name": "Local Chapter 2",
            "chapter_type": "Local",
            "region": "North-A-2",
            "parent_chapter": "District A",
            "published": 1,
            "introduction": "Local chapter 2",
        },
        {
            "name": "Finance Committee",
            "chapter_type": "Committee",
            "region": "National",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Finance and budget committee",
        },
        {
            "name": "Membership Committee",
            "chapter_type": "Committee",
            "region": "National",
            "parent_chapter": "National Chapter",
            "published": 1,
            "introduction": "Membership coordination committee",
        },
    ]


def create_chapter(data):
    """Create or update a single chapter."""
    name = data.get("name")

    if frappe.db.exists("Chapter", name):
        doc = frappe.get_doc("Chapter", name)
        doc.update(data)
        doc.save()
        print(f"  Updated: {name}")
    else:
        doc = frappe.get_doc({"doctype": "Chapter", **data})
        doc.insert()
        print(f"  Created: {name}")


def clear_demo_structure():
    """Remove all demo chapters and chapter types. Use with caution!"""
    print("Clearing demo structure...")

    chapters = frappe.get_all("Chapter", pluck="name")
    for chapter in chapters:
        frappe.delete_doc("Chapter", chapter, ignore_permissions=True)
    print(f"Deleted {len(chapters)} chapters")

    chapter_types = frappe.get_all("Chapter Type", pluck="name")
    for ct in chapter_types:
        frappe.delete_doc("Chapter Type", ct, ignore_permissions=True)
    print(f"Deleted {len(chapter_types)} chapter types")

    frappe.db.commit()
    print("Demo structure cleared")


def create_user_access(user_email, chapter_name, access_level="Full Access"):
    """
	Grant a user access to a chapter via User Permission.

	Access automatically cascades to all descendant chapters.

	Usage: bench --site <site> execute non_profit.fixtures.setup_demo.create_user_access \
			--kwargs "{'user_email': 'user@example.com', 'chapter_name': 'Region North', 'access_level': 'Full Access'}"
	"""
    from non_profit.non_profit.permissions import grant_chapter_access

    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    if not frappe.db.exists("Chapter", chapter_name):
        print(f"Chapter {chapter_name} not found")
        return

    grant_chapter_access(user, chapter_name, access_level)
    frappe.db.commit()

    print(f"Granted access: {user_email} -> {chapter_name} ({access_level})")
    print("Note: Access automatically includes all child chapters")


def revoke_user_access(user_email, chapter_name):
    """
	Revoke a user's access to a chapter.

	Usage: bench --site <site> execute non_profit.fixtures.setup_demo.revoke_user_access \
			--kwargs "{'user_email': 'user@example.com', 'chapter_name': 'Region North'}"
	"""
    from non_profit.non_profit.permissions import revoke_chapter_access

    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    revoke_chapter_access(user, chapter_name)
    frappe.db.commit()

    print(f"Revoked access: {user_email} -> {chapter_name}")


def list_user_access(user_email):
    """
	List all chapter access for a user.

	Usage: bench --site <site> execute non_profit.fixtures.setup_demo.list_user_access \
			--kwargs "{'user_email': 'user@example.com'}"
	"""
    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    permissions = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Chapter"},
        fields=["for_value", "access_level"],
        order_by="for_value",
    )

    if not permissions:
        print(f"No chapter access found for {user_email}")
        return

    print(f"Chapter access for {user_email}:")
    for p in permissions:
        print(f"  {p.for_value}: {p.access_level or 'Read Only'}")
