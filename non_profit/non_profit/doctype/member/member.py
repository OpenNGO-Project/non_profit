# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cstr, getdate, nowdate

try:
    from good_connector.identity_matching import (
        resolve_or_create_contact_from_external_signup,
    )
except ImportError:
    resolve_or_create_contact_from_external_signup = None

from non_profit.non_profit.utils import split_person_name as _split_person_name


class Member(Document):
    def onload(self):
        """Load address and contacts in `__onload`"""
        load_address_and_contact(self)

    def validate(self):
        self.set_member_name_from_customer()
        if not self.member_name:
            frappe.throw(_("Member Name is required."))

        if self.email_id:
            self.validate_email_type(self.email_id)

    def set_member_name_from_customer(self) -> None:
        if self.customer and not cstr(self.member_name).strip():
            self.member_name = _customer_display_name(self.customer)

    def validate_email_type(self, email):
        from frappe.utils import validate_email_address

        validate_email_address(email.strip(), True)

    @frappe.whitelist()
    def make_customer_and_link(self) -> None:
        if self.customer:
            frappe.msgprint(_("A customer is already linked to this Member"))
            return

        customer = create_customer(
            frappe._dict(
                {"fullname": self.member_name, "email": self.email_id, "phone": None}
            )
        )

        self.customer = customer
        self.save()
        frappe.msgprint(
            _("Customer {0} has been created succesfully.").format(self.customer)
        )

    @frappe.whitelist()
    def create_membership(
        self,
        membership_type: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        membership_status: str = "Current",
        keep_to_date_open: bool = True,
    ) -> str:
        membership = get_or_create_membership_for_member(
            self.name,
            membership_type=membership_type,
            from_date=from_date,
            to_date=to_date,
            membership_status=membership_status,
            keep_to_date_open=keep_to_date_open,
        )
        return membership.name


def get_or_create_member_for_customer(
    customer: str,
    membership_type: str | None = None,
    *,
    ignore_permissions: bool = False,
):
    # ``membership_type`` is accepted for compatibility with older callers.
    # Membership Type now belongs only to Membership.
    if not customer:
        frappe.throw(_("Customer is required to create a Member"))

    existing_member = frappe.db.exists("Member", {"customer": customer})
    if existing_member:
        return frappe.get_doc("Member", existing_member)

    customer_name = frappe.db.get_value("Customer", customer, "customer_name")
    if not customer_name:
        frappe.throw(_("Customer {0} does not exist").format(frappe.bold(customer)))

    member = frappe.new_doc("Member")
    member.customer = customer
    member.insert(ignore_permissions=ignore_permissions)
    return member


def get_or_create_member_for_contact(
    contact: str,
    *,
    ignore_permissions: bool = False,
):
    if not contact:
        frappe.throw(_("Contact is required to create a Member"))
    if not frappe.db.exists("Contact", contact):
        frappe.throw(_("Contact {0} does not exist").format(frappe.bold(contact)))

    linked_member = _member_linked_to_contact(contact)
    if linked_member:
        return frappe.get_doc("Member", linked_member)

    contact_doc = frappe.get_doc("Contact", contact)
    email = _contact_email(contact_doc)
    if email:
        existing_member = frappe.db.exists("Member", {"email_id": email})
        if existing_member:
            _link_contact_to_member(contact, existing_member, ignore_permissions=ignore_permissions)
            return frappe.get_doc("Member", existing_member)

    member = frappe.new_doc("Member")
    member.member_name = _contact_display_name(contact_doc)
    member.email_id = email
    member.insert(ignore_permissions=ignore_permissions)
    _link_contact_to_member(contact, member.name, ignore_permissions=ignore_permissions)
    return member


@frappe.whitelist(methods=["POST"])
def create_member_and_membership(
    contact: str | None = None,
    customer: str | None = None,
    membership_type: str | None = None,
) -> dict[str, str | None]:
    contact = (contact or "").strip()
    customer = (customer or "").strip()
    membership_type = (membership_type or "").strip()

    if bool(contact) == bool(customer):
        frappe.throw(_("Select either a Contact or a Customer."))
    if not membership_type:
        frappe.throw(_("Membership Type is required to create a Membership"))

    if contact:
        member = get_or_create_member_for_contact(contact)
    else:
        member = get_or_create_member_for_customer(customer)

    membership = get_or_create_membership_for_member(
        member.name,
        membership_type=membership_type,
        membership_status="Current",
        keep_to_date_open=True,
    )
    return {
        "member": member.name,
        "membership": membership.name,
        "customer": member.customer,
        "contact": contact or None,
        "membership_type": membership.membership_type,
    }


def get_or_create_membership_for_member(
    member: str,
    membership_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    membership_status: str = "Current",
    keep_to_date_open: bool = True,
    *,
    ignore_permissions: bool = False,
):
    if not member:
        frappe.throw(_("Member is required to create a Membership"))

    frappe.get_doc("Member", member)
    membership_type = membership_type or _single_membership_type()
    if not membership_type:
        frappe.throw(_("Membership Type is required to create a Membership"))

    reference_date = getdate(from_date or nowdate())
    existing_membership = _active_membership_for_member(
        member,
        membership_type,
        reference_date,
    )
    if existing_membership:
        return frappe.get_doc("Membership", existing_membership)

    membership = frappe.new_doc("Membership")
    membership.member = member
    membership.membership_type = membership_type
    membership.membership_status = membership_status or "Current"
    membership.from_date = from_date or nowdate()
    if to_date:
        membership.to_date = to_date

    membership_type_amount = frappe.db.get_value(
        "Membership Type", membership_type, "amount"
    )
    if membership_type_amount is not None:
        membership.amount = membership_type_amount

    currency = _membership_currency()
    if currency:
        membership.currency = currency

    if keep_to_date_open and not to_date:
        membership.flags.keep_to_date_open = True

    membership.insert(ignore_permissions=ignore_permissions)
    return membership


def _active_membership_for_member(
    member: str,
    membership_type: str,
    reference_date,
) -> str | None:
    memberships = frappe.get_all(
        "Membership",
        filters={
            "member": member,
            "membership_type": membership_type,
            "membership_status": ["!=", "Cancelled"],
        },
        fields=["name", "from_date", "to_date"],
        order_by="from_date desc, creation desc",
    )

    for membership in memberships:
        if _membership_active_on(membership, reference_date):
            return membership.name

    return None


def _membership_active_on(membership, reference_date) -> bool:
    reference_date = getdate(reference_date)
    from_date = getdate(membership.from_date) if membership.from_date else None
    to_date = getdate(membership.to_date) if membership.to_date else None

    return (not from_date or from_date <= reference_date) and (
        not to_date or to_date >= reference_date
    )


def _membership_currency() -> str | None:
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if company:
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        if company_currency:
            return company_currency

    return frappe.db.get_default("currency")


def _single_membership_type() -> str | None:
    membership_types = frappe.get_all("Membership Type", pluck="name", limit=2)
    if len(membership_types) == 1:
        return membership_types[0]

    return None


def _member_linked_to_contact(contact: str) -> str | None:
    linked_member = frappe.db.get_value(
        "Dynamic Link",
        {
            "parenttype": "Contact",
            "parent": contact,
            "link_doctype": "Member",
        },
        "link_name",
    )
    return linked_member if linked_member and frappe.db.exists("Member", linked_member) else None


def _link_contact_to_member(
    contact: str,
    member: str,
    *,
    ignore_permissions: bool = False,
) -> None:
    if frappe.db.exists(
        "Dynamic Link",
        {
            "parenttype": "Contact",
            "parent": contact,
            "link_doctype": "Member",
            "link_name": member,
        },
    ):
        return

    contact_doc = frappe.get_doc("Contact", contact)
    contact_doc.append("links", {"link_doctype": "Member", "link_name": member})
    contact_doc.save(ignore_permissions=ignore_permissions)


def _contact_email(contact_doc) -> str | None:
    if contact_doc.get("email_id"):
        return contact_doc.email_id
    emails = sorted(
        contact_doc.get("email_ids") or [],
        key=lambda row: (0 if row.get("is_primary") else 1, row.get("idx") or 0),
    )
    return emails[0].email_id if emails else None


def _contact_display_name(contact_doc) -> str:
    full_name = (contact_doc.get("full_name") or "").strip()
    if full_name:
        return full_name
    name_parts = [contact_doc.get("first_name"), contact_doc.get("last_name")]
    return " ".join(part for part in name_parts if part).strip() or contact_doc.name


def _customer_display_name(customer: str) -> str:
    if not frappe.db.exists("Customer", customer):
        frappe.throw(_("Customer {0} does not exist").format(frappe.bold(customer)))
    customer_doc = frappe.get_doc("Customer", customer)
    name = customer_doc.customer_name or customer
    additional = (customer_doc.get("name_additional") or "").strip()
    return f"{name} - {additional}" if additional else name


def _contact_for_email(email: str | None) -> str | None:
    if not email:
        return None
    return frappe.db.get_value(
        "Contact Email",
        {"email_id": email, "parenttype": "Contact"},
        "parent",
    )


def get_or_create_member(user_details):
    user_details = frappe._dict(user_details)
    member_list = frappe.get_all(
        "Member",
        filters={"email_id": user_details.email},
        limit=1,
    )
    if member_list and member_list[0]:
        return member_list[0]["name"]
    else:
        return create_member(user_details)


def create_member(user_details):
    user_details = frappe._dict(user_details)
    customer = create_customer(user_details)
    member = frappe.new_doc("Member")
    member.update(
        {
            "customer": customer,
            "email_id": user_details.email,
        }
    )

    member.insert(ignore_permissions=True)
    contact = _contact_for_email(user_details.email)
    if contact:
        _link_contact_to_member(contact, member.name, ignore_permissions=True)

    return member


def create_customer(user_details, member=None):
    customer = frappe.new_doc("Customer")
    customer.customer_name = user_details.fullname
    customer.customer_type = "Individual"
    customer.customer_group = frappe.db.get_single_value(
        "Selling Settings", "customer_group"
    )
    customer.territory = frappe.db.get_single_value("Selling Settings", "territory")
    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)

    if resolve_or_create_contact_from_external_signup:
        first_name, last_name = _split_person_name(user_details.fullname)
        links = [("Customer", customer.name)]
        if member:
            links.append(("Member", member))
        resolve_or_create_contact_from_external_signup(
            email=user_details.email,
            first_name=first_name,
            last_name=last_name,
            full_name=user_details.fullname,
            phone=user_details.get("mobile") or user_details.get("phone"),
            links=links,
            source_doctype="Member",
            source_name=member,
        )
        return customer.name

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

    except Exception:
        frappe.db.rollback(save_point="contact_creation")
        frappe.log_error(frappe.get_traceback(), _("Contact Creation Failed"))

    return customer.name
