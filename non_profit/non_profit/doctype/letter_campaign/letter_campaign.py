import io
import traceback
import zipfile

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.print_utils import get_print


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
    existing_contacts = {r.contact for r in campaign.recipients}

    for record_name in selected_records:
        if source_doctype == "Member":
            contact_name = get_contact_from_member(record_name)
            member_name = record_name
        else:
            contact_name = record_name
            member_name = get_member_from_contact(contact_name)

        if not contact_name:
            skipped_count += 1
            continue

        if contact_name in existing_contacts:
            continue

        contact = frappe.get_doc("Contact", contact_name)
        address = get_primary_address(contact)

        if not address:
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


def get_contact_from_member(member_name):
    contact = frappe.db.sql(
        """
		SELECT c.name
		FROM `tabContact` c
		INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE dl.link_doctype = 'Member'
		AND dl.link_name = %s
		AND dl.parenttype = 'Contact'
		LIMIT 1
	""",
        member_name,
        as_dict=True,
    )

    return contact[0].name if contact else None


def get_member_from_contact(contact_name):
    member = frappe.db.sql(
        """
		SELECT dl.link_name
		FROM `tabDynamic Link` dl
		WHERE dl.parent = %s
		AND dl.link_doctype = 'Member'
		AND dl.parenttype = 'Contact'
		LIMIT 1
	""",
        contact_name,
        as_dict=True,
    )

    return member[0].link_name if member else None


def get_primary_address(contact):
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
		SELECT DISTINCT m.name, m.member_name, m.email_id
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
