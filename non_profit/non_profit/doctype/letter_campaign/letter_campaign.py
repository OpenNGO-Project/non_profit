import io
import traceback
import zipfile

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.print_utils import get_print

from non_profit.non_profit.doctype.member.member import (
    get_customer_primary_contact,
    get_member_contact,
    get_member_email,
)


class LetterCampaign(Document):
    def validate(self):
        self.update_recipient_count()

    def update_recipient_count(self):
        self.total_recipients = len(self.recipients) if self.recipients else 0

    @frappe.whitelist()
    def generate_pdfs(self):
        if self.status == "Generated":
            frappe.throw(_("PDFs already generated. Create a new campaign."))

        if not self.recipients:
            frappe.throw(_("No recipients added."))

        if not self.print_format:
            frappe.throw(_("Please select a Print Format."))

        pdf_files = []
        generated_count = 0

        for recipient in self.recipients:
            try:
                contact = frappe.get_doc("Contact", recipient.contact)

                pdf_content = get_print(
                    doctype="Contact",
                    name=contact.name,
                    print_format=self.print_format,
                    letterhead=self.letter_head,
                    as_pdf=True,
                )

                file_name = f"{recipient.contact_name or recipient.contact}.pdf"

                pdf_files.append(
                    {"fname": sanitize_filename(file_name), "fcontent": pdf_content}
                )

                recipient.db_set("pdf_generated", 1)
                generated_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to generate PDF for {recipient.contact}\n\nError: {str(e)}\n\nTraceback:\n{traceback.format_exc()}",
                    "Letter Campaign PDF Error",
                )

        if not pdf_files:
            frappe.throw(_("Failed to generate any PDFs. Check Error Log for details."))

        if self.output_type == "Merged PDF":
            output_content = merge_pdfs(pdf_files)
            output_filename = f"{sanitize_filename(self.title)}_merged.pdf"
        else:
            output_content = create_zip(pdf_files)
            output_filename = f"{sanitize_filename(self.title)}.zip"

        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": output_filename,
                "content": output_content,
                "attached_to_doctype": "Letter Campaign",
                "attached_to_name": self.name,
                "is_private": 1,
            }
        ).insert()

        self.db_set("generated_file", file_doc.file_url)
        self.db_set("status", "Generated")

        return {
            "generated": generated_count,
            "total": len(self.recipients),
            "file_url": file_doc.file_url,
        }


def sanitize_filename(filename):
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


def merge_pdfs(pdf_files):
    try:
        from pypdf import PdfMerger
    except ImportError:
        frappe.throw(_("pypdf library is required. Install it with: pip install pypdf"))

    merger = PdfMerger()

    for pdf in pdf_files:
        pdf_stream = io.BytesIO(pdf["fcontent"])
        merger.append(pdf_stream)

    output = io.BytesIO()
    merger.write(output)
    merger.close()

    return output.getvalue()


def create_zip(pdf_files):
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdf_files:
            zf.writestr(pdf["fname"], pdf["fcontent"])

    return zip_buffer.getvalue()


@frappe.whitelist()
def add_recipients(campaign_name, source_doctype, selected_records):
    if isinstance(selected_records, str):
        selected_records = frappe.parse_json(selected_records)

    campaign = frappe.get_doc("Letter Campaign", campaign_name)
    added_count = 0
    skipped_count = 0
    existing_contacts = {r.contact for r in campaign.recipients if r.contact}

    for record_name in selected_records:
        contact_name, member_name = get_contact_and_member(source_doctype, record_name)

        if not contact_name:
            frappe.log_error(
                f"No contact found for {source_doctype}: {record_name}",
                "Letter Campaign Debug",
            )
            skipped_count += 1
            continue

        if contact_name in existing_contacts:
            continue

        contact = frappe.get_doc("Contact", contact_name)
        address = get_primary_address(contact, member_name)

        if not address:
            frappe.log_error(
                f"No address found for contact {contact_name}, member {member_name}, customer {frappe.db.get_value('Member', member_name, 'customer') if member_name else 'N/A'}",
                "Letter Campaign Debug",
            )
            skipped_count += 1
            continue

        membership_type = None
        if member_name:
            active_membership = get_active_membership(member_name)
            if active_membership:
                membership_type = active_membership.membership_type

        address_display = format_address_display(address)

        campaign.append(
            "recipients",
            {
                "contact": contact.name,
                "contact_name": contact.full_name,
                "email": contact.email_id,
                "address": address.name,
                "address_display": address_display,
                "member": member_name,
                "membership_type": membership_type,
                "pdf_generated": 0,
            },
        )
        added_count += 1

    campaign.save()
    return {
        "added": added_count,
        "skipped": skipped_count,
        "total": len(campaign.recipients),
    }


def get_contact_and_member(source_doctype, record_name):
    """Get contact and member for a record based on source doctype.

    Returns:
        Tuple of (contact_name, member_name)
    """
    if source_doctype == "Contact":
        contact_name = record_name
        member_name = get_member_from_contact(contact_name)
        return contact_name, member_name

    if source_doctype == "Member":
        contact_name = get_contact_from_member(record_name)
        member_name = record_name
        return contact_name, member_name

    if source_doctype == "Donor":
        contact_name = get_contact_from_donor(record_name)
        return contact_name, None

    if source_doctype == "Lead":
        contact_name = get_or_create_contact_from_lead(record_name)
        return contact_name, None

    return None, None


@frappe.whitelist()
def add_recipients_by_chapter(campaign_name, chapter):
    """Add recipients from all members in a chapter (including subchapters)."""
    if not chapter:
        return {"added": 0, "skipped": 0, "total": 0}

    chapters = get_chapter_and_descendants(chapter)
    if not chapters:
        return {"added": 0, "skipped": 0, "total": 0}

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

    if not members:
        return {"added": 0, "skipped": 0, "total": 0}

    selected_records = [m.name for m in members]
    return add_recipients(campaign_name, "Member", selected_records)


def get_chapter_and_descendants(chapter_name):
    """Get a chapter and all its descendant chapters using NestedSet."""
    chapter = frappe.db.get_value("Chapter", chapter_name, ["lft", "rgt"], as_dict=True)
    if not chapter:
        return [chapter_name]

    descendants = frappe.db.sql_list(
        "SELECT name FROM `tabChapter` WHERE lft >= %s AND rgt <= %s",
        (chapter.lft, chapter.rgt),
    )

    return descendants


def get_contact_from_donor(donor_name):
    """Get contact linked to a donor via Customer."""
    donor = frappe.db.get_value(
        "Donor", donor_name, ["customer", "email"], as_dict=True
    )
    if not donor:
        return None

    if donor.customer:
        contact = get_contact_for_customer(donor.customer)
        if contact:
            return contact.name

    if donor.email:
        contact = frappe.db.get_value("Contact", {"email_id": donor.email}, "name")
        if contact:
            return contact

    return None


def get_or_create_contact_from_lead(lead_name):
    """Get or create a contact from a lead."""
    lead = frappe.db.get_value(
        "Lead",
        lead_name,
        ["first_name", "last_name", "email_id", "phone", "mobile_no"],
        as_dict=True,
    )
    if not lead or not lead.email_id:
        return None

    existing = frappe.db.get_value("Contact", {"email_id": lead.email_id}, "name")
    if existing:
        return existing

    contact = frappe.new_doc("Contact")
    contact.first_name = lead.first_name or "Unknown"
    contact.last_name = lead.last_name or ""
    contact.email_id = lead.email_id
    if lead.phone:
        contact.phone = lead.phone
    elif lead.mobile_no:
        contact.phone = lead.mobile_no
    contact.insert(ignore_permissions=True)

    return contact.name


def get_contact_for_customer(customer):
    """Get the primary contact for a customer."""
    return get_customer_primary_contact(customer)


def get_contact_from_member(member_name):
    contact = get_member_contact(member_name)
    return contact.name if contact else None


def get_member_from_contact(contact_name):
    customer = frappe.db.get_value(
        "Dynamic Link",
        {
            "parent": contact_name,
            "parenttype": "Contact",
            "link_doctype": "Customer",
        },
        "link_name",
    )

    if not customer:
        return None

    return frappe.db.get_value("Member", {"customer": customer}, "name")


def get_primary_address(contact, member_name=None):
    addresses = frappe.db.sql(
        """
        SELECT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode, a.country
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name
        WHERE dl.link_doctype = 'Contact'
        AND dl.link_name = %s
        AND dl.parenttype = 'Address'
        ORDER BY a.is_primary_address DESC
        LIMIT 1
    """,
        contact.name,
        as_dict=True,
    )

    if addresses:
        return addresses[0]

    linked_entity_addresses = frappe.db.sql(
        """
        SELECT DISTINCT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode, a.country
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` addr_dl ON addr_dl.parent = a.name AND addr_dl.parenttype = 'Address'
        INNER JOIN `tabDynamic Link` contact_dl ON contact_dl.link_doctype = addr_dl.link_doctype
            AND contact_dl.link_name = addr_dl.link_name
            AND contact_dl.parenttype = 'Contact'
        WHERE contact_dl.parent = %s
        ORDER BY a.is_primary_address DESC
        LIMIT 1
    """,
        contact.name,
        as_dict=True,
    )

    if linked_entity_addresses:
        return linked_entity_addresses[0]

    if member_name:
        customer = frappe.db.get_value("Member", member_name, "customer")
        if customer:
            customer_addresses = frappe.db.sql(
                """
                SELECT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode, a.country
                FROM `tabAddress` a
                INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name
                WHERE dl.link_doctype = 'Customer'
                AND dl.link_name = %s
                AND dl.parenttype = 'Address'
                ORDER BY a.is_primary_address DESC
                LIMIT 1
            """,
                customer,
                as_dict=True,
            )
            if customer_addresses:
                return customer_addresses[0]

    return addresses[0] if addresses else None


def format_address_display(address):
    if not address:
        return ""

    parts = []
    if address.address_line1:
        parts.append(address.address_line1)
    if address.address_line2:
        parts.append(address.address_line2)
    if address.city:
        parts.append(address.city)
    if address.state:
        parts.append(address.state)
    if address.pincode:
        parts.append(address.pincode)
    if address.country:
        parts.append(address.country)

    return "\n".join(parts)


def get_active_membership(member_name):
    from frappe.utils import today

    membership = frappe.db.sql(
        """
		SELECT name, membership_type
		FROM `tabMembership`
		WHERE member = %s
		AND docstatus = 1
		AND from_date <= %s
		AND ifnull(to_date, '2099-12-31') >= %s
		ORDER BY from_date DESC
		LIMIT 1
	""",
        (member_name, today(), today()),
        as_dict=True,
    )

    return membership[0] if membership else None


@frappe.whitelist()
def get_membership_types():
    return frappe.get_all("Membership Type", fields=["name"], order_by="name")


@frappe.whitelist()
def get_members_by_membership_type(membership_types):
    if isinstance(membership_types, str):
        membership_types = frappe.parse_json(membership_types)

    if not membership_types:
        return []

    from frappe.utils import today

    members = frappe.db.sql(
        """
		SELECT DISTINCT m.name, m.member_name
		FROM `tabMember` m
		INNER JOIN `tabMembership` ms ON ms.member = m.name
		WHERE ms.docstatus = 1
		AND ms.membership_type IN %s
		AND ms.from_date <= %s
		AND ifnull(ms.to_date, '2099-12-31') >= %s
		ORDER BY m.member_name
	""",
        (tuple(membership_types), today(), today()),
        as_dict=True,
    )

    for member in members:
        member.email = get_member_email(member.name) or ""

    return members


@frappe.whitelist()
def get_contacts_with_address():
    contacts = frappe.db.sql(
        """
        SELECT DISTINCT c.name, c.full_name, c.email_id, a.city, a.country
        FROM `tabContact` c
        INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name
        INNER JOIN `tabAddress` a ON a.name = dl.link_name
        WHERE dl.link_doctype = 'Contact'
        AND dl.parenttype = 'Address'
        AND c.email_id IS NOT NULL
        AND c.email_id != ''
        ORDER BY c.full_name
        LIMIT 500
    """,
        as_dict=True,
    )

    return contacts
