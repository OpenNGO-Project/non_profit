import frappe
from frappe import _
from frappe.model.document import Document


CONTACT_FIELDS = ["name", "full_name", "first_name", "last_name"]


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


def get_contact_details(contact_name: str) -> frappe._dict | None:
    """Return contact details with resolved primary email."""
    if not contact_name:
        return None

    contact = frappe.db.get_value("Contact", contact_name, CONTACT_FIELDS, as_dict=True)
    if not contact:
        return None

    contact = frappe._dict(contact)
    contact.full_name = get_contact_full_name(contact)
    contact.email_id = get_contact_email(contact.name)
    return contact


def get_contact_full_name(contact: frappe._dict | dict | None) -> str | None:
    """Build a usable display name for a contact."""
    if not contact:
        return None

    full_name = (contact.get("full_name") or "").strip()
    if full_name:
        return full_name

    full_name = " ".join(
        part.strip()
        for part in [contact.get("first_name") or "", contact.get("last_name") or ""]
        if part and part.strip()
    ).strip()

    return full_name or None


def get_customer_contact_names(customer: str) -> list[str]:
    """Return all contacts linked to a customer."""
    if not customer:
        return []

    return frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer,
            "parenttype": "Contact",
        },
        pluck="parent",
    )


def is_contact_linked_to_customer(contact_name: str, customer: str) -> bool:
    """Check whether a contact belongs to the customer."""
    if not contact_name or not customer:
        return False

    return bool(
        frappe.db.exists(
            "Dynamic Link",
            {
                "parent": contact_name,
                "parenttype": "Contact",
                "link_doctype": "Customer",
                "link_name": customer,
            },
        )
    )


def get_customer_primary_contact(customer: str) -> frappe._dict | None:
    """Get the primary contact for the linked customer."""
    contact_names = get_customer_contact_names(customer)
    if not contact_names:
        return None

    primary_contact = frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names], "is_primary_contact": 1},
        CONTACT_FIELDS,
        as_dict=True,
    )

    if primary_contact:
        return get_contact_details(primary_contact.name)

    first_contact = frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names]},
        CONTACT_FIELDS,
        as_dict=True,
    )
    if first_contact:
        return get_contact_details(first_contact.name)

    return None


def get_member_contact(member_name: str) -> frappe._dict | None:
    """Resolve the preferred billing/contact person for a member."""
    member = frappe.db.get_value(
        "Member",
        member_name,
        ["customer", "designated_representative"],
        as_dict=True,
    )
    if not member:
        return None

    if member.designated_representative and is_contact_linked_to_customer(
        member.designated_representative, member.customer
    ):
        return get_contact_details(member.designated_representative)

    return get_customer_primary_contact(member.customer)


def get_member_email(member_name: str) -> str | None:
    """Return the resolved email address for a member."""
    contact = get_member_contact(member_name)
    return contact.email_id if contact else None


class Member(Document):
    def validate(self):
        if not self.customer:
            frappe.throw(_("Customer is required"))

        self.validate_unique_customer()
        self.validate_designated_representative()
        self.member_name = self.get_derived_member_name()

    def validate_unique_customer(self):
        filters = {"customer": self.customer}
        if not self.is_new():
            filters["name"] = ["!=", self.name]

        if frappe.db.exists("Member", filters):
            frappe.throw(
                _("Customer {0} already has a Member profile.").format(
                    frappe.bold(self.customer)
                )
            )

    def validate_designated_representative(self):
        if not self.designated_representative:
            return

        if not is_contact_linked_to_customer(
            self.designated_representative, self.customer
        ):
            frappe.throw(
                _(
                    "Designated Representative must be a Contact linked to Customer {0}."
                ).format(frappe.bold(self.customer))
            )

    def get_designated_representative_contact(self):
        if not self.designated_representative:
            return None

        return get_contact_details(self.designated_representative)

    def get_primary_contact_for_customer(self):
        return get_customer_primary_contact(self.customer)

    def get_preferred_contact(self):
        return (
            self.get_designated_representative_contact()
            or self.get_primary_contact_for_customer()
        )

    def get_derived_member_name(self) -> str:
        customer = frappe.db.get_value(
            "Customer", self.customer, ["customer_name", "customer_type"], as_dict=True
        )
        if not customer:
            frappe.throw(_("Customer {0} does not exist.").format(self.customer))

        if customer.customer_type == "Company":
            return customer.customer_name

        contact = self.get_preferred_contact()
        return get_contact_full_name(contact) or customer.customer_name

    @frappe.whitelist()
    def get_contact_details(self):
        """API method to fetch the resolved contact and derived member name."""
        if not self.customer:
            return {
                "designated_representative": "",
                "resolved_contact": "",
                "contact_name": "",
                "email_id": "",
                "member_name": "",
                "has_contact": False,
            }

        contact = self.get_preferred_contact()
        if contact:
            return {
                "designated_representative": self.designated_representative or "",
                "resolved_contact": contact.name,
                "contact_name": contact.full_name or "",
                "email_id": contact.email_id or "",
                "member_name": self.get_derived_member_name(),
                "has_contact": True,
            }

        return {
            "email_id": "",
            "designated_representative": self.designated_representative or "",
            "resolved_contact": "",
            "contact_name": "",
            "member_name": self.get_derived_member_name(),
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
    """Get existing member by linked customer or create one."""
    customer = None

    if user_details.email:
        contact_name = frappe.db.get_value(
            "Contact Email", {"email_id": user_details.email}, "parent"
        )
        if contact_name:
            customer = frappe.db.get_value(
                "Dynamic Link",
                {
                    "parent": contact_name,
                    "parenttype": "Contact",
                    "link_doctype": "Customer",
                },
                "link_name",
            )

    if customer:
        member_name = frappe.db.get_value("Member", {"customer": customer}, "name")
        if member_name:
            return member_name

    return create_member(user_details)


def create_member(user_details):
    """Create a new Member with linked Customer and Contact."""
    user_details = frappe._dict(user_details)
    customer, _contact = create_customer(user_details)

    member = frappe.new_doc("Member")
    member.customer = customer
    member.insert(ignore_permissions=True)

    return member


def create_customer(user_details):
    """Create a Customer with an optional Contact."""
    customer = frappe.new_doc("Customer")
    customer.customer_name = user_details.fullname
    customer.customer_type = "Individual"
    customer.customer_group = frappe.db.get_single_value(
        "Selling Settings", "customer_group"
    )
    customer.territory = frappe.db.get_single_value("Selling Settings", "territory")
    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)

    contact_name = None

    try:
        if user_details.email or user_details.mobile:
            frappe.db.savepoint("contact_creation")
            contact = frappe.new_doc("Contact")
            contact.first_name = user_details.fullname
            if user_details.mobile:
                contact.add_phone(
                    user_details.mobile, is_primary_phone=1, is_primary_mobile_no=1
                )
            if user_details.email:
                contact.add_email(user_details.email, is_primary=1)
            contact.append(
                "links", {"link_doctype": "Customer", "link_name": customer.name}
            )
            contact.insert(ignore_permissions=True)
            contact_name = contact.name

    except frappe.DuplicateEntryError:
        if user_details.email:
            existing_contact = frappe.db.get_value(
                "Contact Email", {"email_id": user_details.email}, "parent"
            )
            if existing_contact and not is_contact_linked_to_customer(
                existing_contact, customer.name
            ):
                contact = frappe.get_doc("Contact", existing_contact)
                contact.append(
                    "links", {"link_doctype": "Customer", "link_name": customer.name}
                )
                contact.save(ignore_permissions=True)
            contact_name = existing_contact

    except Exception:
        frappe.db.rollback(save_point="contact_creation")
        frappe.log_error(frappe.get_traceback(), _("Contact Creation Failed"))

    return customer.name, contact_name
