# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Donor(Document):
    def validate(self):
        self.validate_email()
        self.validate_required_fields()

    def validate_email(self):
        if self.email:
            from frappe.utils import validate_email_address

            validate_email_address(self.email.strip(), True)

    def validate_required_fields(self):
        if not self.donor_type:
            frappe.throw(_("Donor Type is required"))
        if not self.customer:
            frappe.throw(_("Customer is required"))
        if not self.contact:
            frappe.throw(_("Contact is required"))

    def on_update(self):
        self.update_contact_dynamic_links()

    def update_contact_dynamic_links(self):
        if not self.contact:
            return

        contact = frappe.get_doc("Contact", self.contact)
        links_to_add = []

        if not any(
            l.link_doctype == "Donor" and l.link_name == self.name
            for l in (contact.links or [])
        ):
            links_to_add.append(
                {
                    "link_doctype": "Donor",
                    "link_name": self.name,
                    "link_title": self.donor_name,
                }
            )

        if self.customer and not any(
            l.link_doctype == "Customer" and l.link_name == self.customer
            for l in (contact.links or [])
        ):
            links_to_add.append(
                {
                    "link_doctype": "Customer",
                    "link_name": self.customer,
                }
            )

        if links_to_add:
            for link in links_to_add:
                contact.append("links", link)
            contact.save(ignore_permissions=True)


def get_or_create_donor(email: str, donor_type: str = None) -> Document:
    """
    Get existing donor by email or create new one.

    Args:
            email: Donor email address
            donor_type: Optional donor type (uses default from settings if not provided)

    Returns:
            Donor document
    """
    existing = frappe.db.get_value("Donor", {"email": email})
    if existing:
        return frappe.get_doc("Donor", existing)

    return create_donor_with_contact_and_customer(email, donor_type)


def create_donor_with_contact_and_customer(
    email: str, donor_type: str = None, donor_name: str = None
) -> Document:
    """
    Create a new Donor with Contact and Customer.

    Args:
            email: Donor email address
            donor_type: Optional donor type (uses default from settings if not provided)
            donor_name: Optional donor name (defaults to email username)

    Returns:
            Donor document
    """
    if not donor_type:
        donor_type = frappe.db.get_single_value(
            "Non Profit Settings", "default_donor_type"
        )

    if not donor_name:
        donor_name = email.split("@")[0]

    contact = frappe.new_doc("Contact")
    contact.first_name = donor_name
    contact.add_email(email, is_primary=1)
    contact.insert(ignore_permissions=True)

    customer = frappe.new_doc("Customer")
    customer.customer_name = donor_name
    customer.customer_type = "Individual"
    customer.insert(ignore_permissions=True)

    contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})
    contact.save(ignore_permissions=True)

    donor = frappe.new_doc("Donor")
    donor.donor_name = donor_name
    donor.donor_type = donor_type
    donor.contact = contact.name
    donor.customer = customer.name
    donor.insert(ignore_permissions=True)

    return donor
