# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cstr

from non_profit.non_profit.doctype.donor.donor import (
	_check_identity_doc_permission,
	ensure_contact_link,
	get_contact_display_name,
	get_contact_email,
)
from non_profit.non_profit.utils import (
	ensure_canonical_contact_available,
	ensure_person_contact,
	validate_person_role_contact_change,
)


class Volunteer(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self) -> None:
		validate_person_role_contact_change(self)
		if self.contact:
			ensure_person_contact(self.contact)


@frappe.whitelist(methods=["POST"])
def create_volunteer_from_contact(contact: str, volunteer_type: str) -> dict[str, str | None]:
	contact = cstr(contact).strip()
	volunteer_type = cstr(volunteer_type).strip()
	if not contact:
		frappe.throw(_("Contact is required to create a Volunteer"))
	if not frappe.db.exists("Contact", contact):
		frappe.throw(_("Contact {0} does not exist").format(frappe.bold(contact)))
	if not volunteer_type:
		frappe.throw(_("Volunteer Type is required to create a Volunteer"))
	if not frappe.db.exists("Volunteer Type", volunteer_type):
		frappe.throw(_("Volunteer Type {0} does not exist").format(frappe.bold(volunteer_type)))
	frappe.has_permission("Volunteer", "create", throw=True)
	_check_identity_doc_permission("Contact", contact, "write")
	_check_identity_doc_permission("Volunteer Type", volunteer_type, "read")
	ensure_person_contact(contact)

	linked_volunteer = _volunteer_linked_to_contact(contact)
	if linked_volunteer:
		frappe.get_doc("Volunteer", linked_volunteer).check_permission("read")
		_set_volunteer_contact(linked_volunteer, contact)
		return {"volunteer": linked_volunteer, "contact": contact}

	contact_doc = frappe.get_doc("Contact", contact)
	email = get_contact_email(contact_doc)
	if not email:
		frappe.throw(_("Contact must have an email address to create a Volunteer"))

	existing_volunteer = frappe.db.exists("Volunteer", {"email": email})
	if existing_volunteer:
		frappe.get_doc("Volunteer", existing_volunteer).check_permission("read")
		_set_volunteer_contact(existing_volunteer, contact)
		return {"volunteer": existing_volunteer, "contact": contact}

	volunteer = frappe.new_doc("Volunteer")
	volunteer.volunteer_name = get_contact_display_name(contact_doc)
	volunteer.volunteer_type = volunteer_type
	volunteer.email = email
	volunteer.contact = contact
	volunteer.insert()
	ensure_contact_link(contact, "Volunteer", volunteer.name)
	return {"volunteer": volunteer.name, "contact": contact}


def _volunteer_linked_to_contact(contact: str) -> str | None:
	if volunteer := frappe.db.get_value("Volunteer", {"contact": contact}, "name"):
		return volunteer
	volunteer = frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "parent": contact, "link_doctype": "Volunteer"},
		"link_name",
		order_by="idx asc",
	)
	return volunteer if volunteer and frappe.db.exists("Volunteer", volunteer) else None


def _set_volunteer_contact(volunteer: str, contact: str) -> None:
	ensure_person_contact(contact)
	ensure_canonical_contact_available("Volunteer", volunteer, contact)
	frappe.db.set_value("Volunteer", volunteer, "contact", contact, update_modified=False)
	ensure_contact_link(contact, "Volunteer", volunteer)
