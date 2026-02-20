import contextlib

import frappe
from frappe import _
from frappe.utils import parse_addr, validate_email_address


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
        SELECT DISTINCT m.name, m.email_id, m.customer
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
        AND m.email_id IS NOT NULL
        AND m.email_id != ''
    """,
        as_dict=True,
    )

    added = 0
    for member in members:
        if not member.email_id:
            continue

        email = parse_addr(member.email_id)[1] if member.email_id else None
        if not email:
            continue

        contact = get_contact_for_customer(member.customer)

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
        record = frappe.db.get_value(
            "Member", record_name, ["email_id", "customer"], as_dict=True
        )
        if not record or not record.email_id:
            return None, None

        email = parse_addr(record.email_id)[1]
        contact = get_contact_for_customer(record.customer)
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
    if not customer:
        return None

    contact_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer,
            "parenttype": "Contact",
        },
        fields=["parent"],
        pluck="parent",
    )

    if not contact_names:
        return None

    primary_contact = frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names], "is_primary_contact": 1},
        ["name", "first_name", "last_name"],
        as_dict=True,
    )

    if primary_contact:
        return primary_contact

    return frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names]},
        ["name", "first_name", "last_name"],
        as_dict=True,
    )


def update_total_subscribers(email_group):
    """Update the total subscribers count on the Email Group."""
    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmail Group Member` WHERE email_group = %s",
        email_group,
    )[0][0]
    frappe.db.set_value("Email Group", email_group, "total_subscribers", total)
