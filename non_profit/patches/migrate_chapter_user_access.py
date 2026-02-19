"""
Migrate Chapter User Access records to User Permission.

This patch migrates existing Chapter User Access records to User Permission
with the custom access_level field.

Run: bench --site <site> execute non_profit.patches.migrate_chapter_user_access.execute
"""

import frappe


def execute():
    """Migrate Chapter User Access to User Permission."""

    if not frappe.db.exists("DocType", "Chapter User Access"):
        print("Chapter User Access DocType not found - migration not needed")
        return

    accesses = frappe.get_all(
        "Chapter User Access",
        fields=["user", "chapter", "access_level"],
        ignore_permissions=True,
    )

    if not accesses:
        print("No Chapter User Access records to migrate")
        return

    migrated = 0
    skipped = 0

    for access in accesses:
        existing = frappe.db.exists(
            "User Permission",
            {"user": access.user, "allow": "Chapter", "for_value": access.chapter},
        )

        if existing:
            skipped += 1
            continue

        try:
            frappe.get_doc(
                {
                    "doctype": "User Permission",
                    "user": access.user,
                    "allow": "Chapter",
                    "for_value": access.chapter,
                    "access_level": access.access_level or "Read Only",
                }
            ).insert(ignore_permissions=True)
            migrated += 1
            print(
                f"  Migrated: {access.user} -> {access.chapter} ({access.access_level})"
            )
        except Exception as e:
            print(f"  Error migrating {access.user} -> {access.chapter}: {e}")

    frappe.db.commit()
    print(f"\nMigration complete: {migrated} migrated, {skipped} skipped")
