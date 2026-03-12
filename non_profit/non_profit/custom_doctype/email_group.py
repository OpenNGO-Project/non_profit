import contextlib

import frappe
from frappe import _
from frappe.utils import parse_addr, validate_email_address

from non_profit.non_profit.doctype.member.member import (
    get_customer_primary_contact,
    get_member_contact,
    get_member_email,
)


@frappe.whitelist()
def import_selected_subscribers(email_group, source_doctype, selected_records):
    """
    Import selected records as Email Group Members.

    First name and last name are fetched dynamically from the linked Contact
    via fetch_from in the custom field definition.

    Args:
        email_group: Name of Email Group
        source_doctype: Source DocType (Contact, Member, Donor, Lead, etc.)
        selected_records: List of record names to import
    """
    if not isinstance(selected_records, list):
        selected_records = frappe.parse_json(selected_records)

    if not selected_records:
        return 0

    added = 0

    for record_name in selected_records:
        email, contact = get_email_and_contact(source_doctype, record_name)
        if not email:
            continue

        with contextlib.suppress(
            frappe.UniqueValidationError, frappe.InvalidEmailAddressError
        ):
            if not frappe.db.exists(
                "Email Group Member", {"email_group": email_group, "email": email}
            ):
                frappe.get_doc(
                    {
                        "doctype": "Email Group Member",
                        "email_group": email_group,
                        "email": email,
                        "contact": contact,
                    }
                ).insert(ignore_permissions=True)
                added += 1

    if added > 0:
        update_total_subscribers(email_group)

    return added


@frappe.whitelist()
def import_members_by_chapter(email_group, chapter):
    """
    Import all members from a chapter (including subchapters) as Email Group Members.

    First name and last name are fetched dynamically from the linked Contact
    via fetch_from in the custom field definition.

    Args:
        email_group: Name of Email Group
        chapter: Name of the chapter to import members from
    """
    if not chapter:
        return 0

    chapters = get_chapter_and_descendants(chapter)
    if not chapters:
        return 0

    chapter_list = "', '".join([c.replace("'", "''") for c in chapters])

    members = frappe.db.sql(
        f"""
        SELECT DISTINCT m.name
        FROM `tabMember` m
        WHERE (
            m.primary_chapter IN ('{chapter_list}')
            OR EXISTS (
                SELECT 1 FROM `tabChapter Member Role` cr
                WHERE cr.parent = m.name
                AND cr.chapter IN ('{chapter_list}')
                AND cr.is_active = 1
            )
        )
    """,
        as_dict=True,
    )

    added = 0
    for member in members:
        email = get_member_email(member.name)
        if not email:
            continue

        email = parse_addr(email)[1]
        contact = get_member_contact(member.name)

        with contextlib.suppress(
            frappe.UniqueValidationError, frappe.InvalidEmailAddressError
        ):
            if not frappe.db.exists(
                "Email Group Member", {"email_group": email_group, "email": email}
            ):
                frappe.get_doc(
                    {
                        "doctype": "Email Group Member",
                        "email_group": email_group,
                        "email": email,
                        "contact": contact.name if contact else None,
                    }
                ).insert(ignore_permissions=True)
                added += 1

    if added > 0:
        update_total_subscribers(email_group)

    return added


def get_email_and_contact(
    doctype: str, record_name: str
) -> tuple[str | None, str | None]:
    """
    Get email and contact for a record.

    Returns:
        Tuple of (email, contact_name)
    """
    if doctype == "Contact":
        record = frappe.db.get_value(
            "Contact", record_name, ["email_id", "name"], as_dict=True
        )
        if record and record.email_id:
            email = parse_addr(record.email_id)[1]
            return email, record.name
        return None, None

    if doctype == "Member":
        email = get_member_email(record_name)
        if not email:
            return None, None

        email = parse_addr(email)[1]
        contact = get_member_contact(record_name)
        return email, contact.name if contact else None

    if doctype == "Donor":
        record = frappe.db.get_value("Donor", record_name, ["email"], as_dict=True)
        if record and record.email:
            email = parse_addr(record.email)[1]
            return email, None
        return None, None

    if doctype == "Lead":
        record = frappe.db.get_value("Lead", record_name, ["email_id"], as_dict=True)
        if record and record.email_id:
            email = parse_addr(record.email_id)[1]
            return email, None
        return None, None

    return None, None


def get_chapter_and_descendants(chapter_name: str) -> list[str]:
    """Get a chapter and all its descendant chapters using NestedSet."""
    chapter = frappe.db.get_value("Chapter", chapter_name, ["lft", "rgt"], as_dict=True)
    if not chapter:
        return [chapter_name]

    descendants = frappe.db.sql_list(
        "SELECT name FROM `tabChapter` WHERE lft >= %s AND rgt <= %s",
        (chapter.lft, chapter.rgt),
    )

    return descendants


def get_contact_for_customer(customer: str) -> dict | None:
    """Get the primary contact for a customer."""
    return get_customer_primary_contact(customer)


def update_total_subscribers(email_group):
    """Update the total subscribers count on the Email Group."""
    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmail Group Member` WHERE email_group = %s",
        email_group,
    )[0][0]
    frappe.db.set_value("Email Group", email_group, "total_subscribers", total)
