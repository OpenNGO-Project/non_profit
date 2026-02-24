# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Volunteer(Document):
    def validate(self):
        self.validate_required_fields()

    def validate_required_fields(self):
        if not self.volunteer_type:
            frappe.throw(_("Volunteer Type is required"))
        if not self.contact:
            frappe.throw(_("Contact is required"))

    def on_update(self):
        self.update_contact_dynamic_link()

    def update_contact_dynamic_link(self):
        if not self.contact:
            return

        contact = frappe.get_doc("Contact", self.contact)

        if not any(
            l.link_doctype == "Volunteer" and l.link_name == self.name
            for l in (contact.links or [])
        ):
            contact.append(
                "links",
                {
                    "link_doctype": "Volunteer",
                    "link_name": self.name,
                    "link_title": self.volunteer_name,
                },
            )
            contact.save(ignore_permissions=True)
