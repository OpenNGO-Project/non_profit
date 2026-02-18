import contextlib

import frappe
from frappe import _
from frappe.utils import parse_addr, validate_email_address


@frappe.whitelist()
def import_selected_subscribers(email_group, source_doctype, selected_records):
    """
    Import selected records as Email Group Members with name fields.

    Args:
            email_group: Name of Email Group
            source_doctype: Source DocType (Contact, Member, Donor, Lead, etc.)
            selected_records: List of record names to import
    """
    if not isinstance(selected_records, list):
        selected_records = frappe.parse_json(selected_records)

    if not selected_records:
        return 0

    field_mapping = get_field_mapping(source_doctype)
    added = 0

    for record_name in selected_records:
        record_data = get_record_data(source_doctype, record_name, field_mapping)
        if not record_data.get("email"):
            continue

        email = (
            parse_addr(record_data.get("email"))[1]
            if record_data.get("email")
            else None
        )
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
                        "first_name": record_data.get("first_name"),
                        "last_name": record_data.get("last_name"),
                    }
                ).insert(ignore_permissions=True)
                added += 1

    if added > 0:
        update_total_subscribers(email_group)

    return added


def get_field_mapping(doctype):
    """Return field mapping for the given doctype."""
    mappings = {
        "Contact": {
            "email_field": "email_id",
            "first_name_field": "first_name",
            "last_name_field": "last_name",
            "fields_to_fetch": ["name", "email_id", "first_name", "last_name"],
        },
        "Member": {
            "email_field": "email_id",
            "first_name_field": "first_name",
            "last_name_field": "last_name",
            "fields_to_fetch": [
                "name",
                "email_id",
                "first_name",
                "last_name",
                "member_name",
            ],
        },
        "Donor": {
            "email_field": "email",
            "first_name_field": None,
            "last_name_field": None,
            "fields_to_fetch": ["name", "email", "donor_name"],
        },
        "Lead": {
            "email_field": "email_id",
            "first_name_field": "first_name",
            "last_name_field": "last_name",
            "fields_to_fetch": ["name", "email_id", "first_name", "last_name"],
        },
    }
    return mappings.get(doctype, {})


def get_record_data(doctype, record_name, field_mapping):
    """Fetch record data from the source doctype."""
    if not field_mapping:
        return {}

    fields_to_fetch = field_mapping.get("fields_to_fetch", ["name"])
    record = frappe.db.get_value(doctype, record_name, fields_to_fetch, as_dict=True)

    if not record:
        return {}

    data = {
        "email": record.get(field_mapping.get("email_field")),
        "first_name": record.get(field_mapping.get("first_name_field")),
        "last_name": record.get(field_mapping.get("last_name_field")),
    }

    if doctype == "Member" and not data.get("first_name") and record.get("member_name"):
        name_parts = record.get("member_name", "").split(" ", 1)
        data["first_name"] = name_parts[0]
        data["last_name"] = name_parts[1] if len(name_parts) > 1 else ""

    if doctype == "Donor" and not data.get("first_name") and record.get("donor_name"):
        name_parts = record.get("donor_name", "").split(" ", 1)
        data["first_name"] = name_parts[0]
        data["last_name"] = name_parts[1] if len(name_parts) > 1 else ""

    return data


def update_total_subscribers(email_group):
    """Update the total subscribers count on the Email Group."""
    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmail Group Member` WHERE email_group = %s",
        email_group,
    )[0][0]
    frappe.db.set_value("Email Group", email_group, "total_subscribers", total)


@frappe.whitelist()
def set_full_name(doc, method=None):
    """Set full_name field based on first_name and last_name."""
    if hasattr(doc, "first_name") and hasattr(doc, "last_name"):
        parts = [doc.first_name, doc.last_name]
        doc.full_name = " ".join(part for part in parts if part).strip()


def get_linked_contact(link_doctype, link_name):
    """Get the Contact linked to a document via Dynamic Link."""
    contact = frappe.db.sql(
        """
		SELECT c.name, c.first_name, c.last_name, c.email_id
		FROM `tabContact` c
		INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE dl.link_doctype = %s
		AND dl.link_name = %s
		AND dl.parenttype = 'Contact'
		LIMIT 1
	""",
        (link_doctype, link_name),
        as_dict=True,
    )

    return contact[0] if contact else None
