# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

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

        if self.email_id:
            self.validate_email_type(self.email_id)

    def set_member_name_from_customer(self) -> None:
        if self.member_name or not self.customer:
            return

        self.member_name = (
            frappe.db.get_value("Customer", self.customer, "customer_name")
            or self.customer
        )

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
    if not customer:
        frappe.throw(_("Customer is required to create a Member"))

    existing_member = frappe.db.exists("Member", {"customer": customer})
    if existing_member:
        return frappe.get_doc("Member", existing_member)

    customer_name = frappe.db.get_value("Customer", customer, "customer_name")
    if not customer_name:
        frappe.throw(_("Customer {0} does not exist").format(frappe.bold(customer)))

    membership_type = membership_type or _single_membership_type()
    if not membership_type:
        frappe.throw(_("Membership Type is required to create a Member"))

    member = frappe.new_doc("Member")
    member.customer = customer
    member.member_name = customer_name
    member.membership_type = membership_type
    member.insert(ignore_permissions=ignore_permissions)
    return member


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

    member_doc = frappe.get_doc("Member", member)
    membership_type = membership_type or member_doc.membership_type
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


def get_or_create_member(user_details):
    membership_type = user_details.get("membership_type")
    member_list = frappe.get_all(
        "Member",
        filters={
            "email_id": user_details.email,
            "membership_type": membership_type,
        },
    )
    if member_list and member_list[0]:
        return member_list[0]["name"]
    else:
        return create_member(user_details)


def create_member(user_details):
    user_details = frappe._dict(user_details)
    membership_type = user_details.get("membership_type")
    member = frappe.new_doc("Member")
    member.update(
        {
            "member_name": user_details.fullname,
            "email_id": user_details.email,
            "membership_type": membership_type,
        }
    )

    member.insert(ignore_permissions=True)
    member.customer = create_customer(user_details, member.name)
    member.save(ignore_permissions=True)

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
