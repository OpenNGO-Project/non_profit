import frappe
from frappe import _
from frappe.model.document import Document


def get_contact_email(contact_name: str) -> str | None:
    """Get the primary email for a contact."""
    if not contact_name:
        return None

    email = frappe.db.get_value(
        "Contact Email",
        {"parent": contact_name, "is_primary": 1},
        "email_id",
    )

    if not email:
        email = frappe.db.get_value(
            "Contact Email",
            {"parent": contact_name},
            "email_id",
        )

    return email


class Member(Document):
    def validate(self):
        if not self.customer:
            frappe.throw(_("Customer is required"))

        if self.email_id:
            self.validate_email_type(self.email_id)

        self.fetch_contact_details()

    def validate_email_type(self, email):
        from frappe.utils import validate_email_address

        validate_email_address(email.strip(), True)

    def fetch_contact_details(self):
        """Fetch first_name, last_name and email_id from Contact linked to Customer."""
        if self.customer and not self.first_name:
            contact = self.get_primary_contact_for_customer()
            if contact:
                self.first_name = contact.first_name or ""
                self.last_name = contact.last_name or ""
                self.contact = contact.name
                self.email_id = contact.email_id or ""

    def get_primary_contact_for_customer(self):
        """Get the primary contact for the linked customer."""
        contact_names = frappe.get_all(
            "Dynamic Link",
            filters={
                "link_doctype": "Customer",
                "link_name": self.customer,
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
            primary_contact.email_id = get_contact_email(primary_contact.name)
            return primary_contact

        first_contact = frappe.db.get_value(
            "Contact",
            {"name": ["in", contact_names]},
            ["name", "first_name", "last_name"],
            as_dict=True,
        )
        if first_contact:
            first_contact.email_id = get_contact_email(first_contact.name)
        return first_contact

    @frappe.whitelist()
    def get_contact_details(self):
        """API method to fetch contact details from customer (called from JS)."""
        if not self.customer:
            return {
                "first_name": "",
                "last_name": "",
                "email_id": "",
                "contact": "",
                "has_contact": False,
            }

        contact = self.get_primary_contact_for_customer()
        if contact:
            return {
                "contact": contact.name,
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "email_id": contact.email_id or "",
                "has_contact": True,
            }
        return {
            "first_name": "",
            "last_name": "",
            "email_id": "",
            "contact": "",
            "has_contact": False,
        }

    @frappe.whitelist()
    def get_active_memberships(self) -> list[dict]:
        """Get all active (submitted) memberships for this member."""
        return frappe.get_all(
            "Membership",
            filters={"member": self.name, "docstatus": 1},
            fields=[
                "name",
                "membership_type",
                "subscription_status",
                "member_since_date",
                "auto_renew",
            ],
            order_by="creation DESC",
        )

    @frappe.whitelist()
    def get_primary_membership(self) -> dict | None:
        """Get the most recent active membership."""
        memberships = self.get_active_memberships()
        return memberships[0] if memberships else None


def get_or_create_member(user_details):
    """Get existing member by email or create new one."""
    member_list = frappe.get_all(
        "Member",
        filters={"email_id": user_details.email},
    )
    if member_list and member_list[0]:
        return member_list[0]["name"]
    else:
        return create_member(user_details)


def create_member(user_details):
    """Create a new Member with linked Customer and Contact."""
    user_details = frappe._dict(user_details)
    member = frappe.new_doc("Member")
    member.update(
        {
            "member_name": user_details.fullname,
            "email_id": user_details.email,
        }
    )

    member.insert(ignore_permissions=True)
    member.customer = create_customer(user_details, member.name)
    member.save(ignore_permissions=True)

    return member


def create_customer(user_details, member=None):
    """Create a Customer with optional Contact for the member."""
    customer = frappe.new_doc("Customer")
    customer.customer_name = user_details.fullname
    customer.customer_type = "Individual"
    customer.customer_group = frappe.db.get_single_value(
        "Selling Settings", "customer_group"
    )
    customer.territory = frappe.db.get_single_value("Selling Settings", "territory")
    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)

    try:
        frappe.db.savepoint("contact_creation")
        contact = frappe.new_doc("Contact")
        contact.first_name = user_details.fullname
        if user_details.mobile:
            contact.add_phone(
                user_details.mobile, is_primary_phone=1, is_primary_mobile_no=1
            )
        if user_details.email:
            contact.add_email(user_details.email, is_primary=1)
        contact.insert(ignore_permissions=True)

        contact.append(
            "links", {"link_doctype": "Customer", "link_name": customer.name}
        )

        if member:
            contact.append("links", {"link_doctype": "Member", "link_name": member})

        contact.save(ignore_permissions=True)

    except frappe.DuplicateEntryError:
        return customer.name

    except Exception as e:
        frappe.db.rollback(save_point="contact_creation")
        frappe.log_error(frappe.get_traceback(), _("Contact Creation Failed"))
        pass

    return customer.name
