# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cstr

try:
    from good_connector.identity_matching import (
        resolve_or_create_contact_from_external_signup,
    )
except ImportError:
    resolve_or_create_contact_from_external_signup = None


class Donor(Document):
    def onload(self):
        """Load address and contacts in `__onload`"""
        load_address_and_contact(self)

    @frappe.whitelist()
    def make_customer_and_link(self: "Donor") -> None:
        if self.customer:
            frappe.msgprint(_("A customer is already linked to this Donor"))
            return

        self.customer = get_or_create_customer_for_donor(self)
        self.save()
        frappe.msgprint(
            _("Customer {0} has been created successfully.").format(self.customer)
        )


def get_or_create_customer_for_donor(donor, email: str | None = None) -> str:
    if isinstance(donor, str):
        donor = frappe.get_doc("Donor", donor)
    email = _normalize_email(email, validate=True) or _legacy_donor_email(donor)

    if donor.get("customer") and frappe.db.exists("Customer", donor.customer):
        _link_contact_and_address_to_customer(donor, donor.customer, email=email)
        return donor.customer

    customer = _customer_for_email(email)
    if not customer:
        customer = _create_customer_for_donor(donor)

    if donor.get("customer") != customer:
        frappe.db.set_value(
            "Donor", donor.name, "customer", customer, update_modified=False
        )
        donor.customer = customer

    _link_contact_and_address_to_customer(donor, customer, email=email)
    return customer


def find_donor_by_email(email: str | None) -> str | None:
    email = _normalize_email(email, validate=True)
    if not email:
        return None

    for customer in _customers_for_email(email):
        donor = frappe.db.get_value(
            "Donor", {"customer": customer}, "name", order_by="modified desc"
        )
        if donor:
            return donor

    return _legacy_donor_name_for_email(email)


def get_donor_email(donor) -> str | None:
    if not donor:
        return None

    if isinstance(donor, str):
        customer = frappe.db.get_value("Donor", donor, "customer")
        donor_name = donor
    else:
        customer = donor.get("customer")
        donor_name = donor.name

    if customer:
        email = _normalize_email(frappe.db.get_value("Customer", customer, "email_id"))
        if email:
            return email

    return _legacy_donor_email(donor if not isinstance(donor, str) else donor_name)


def backfill_donor_customers(limit: int | None = None) -> dict[str, int]:
    if limit is not None and limit <= 0:
        return {"processed": 0, "linked": 0, "failed": 0}

    filters = {"customer": ["in", ["", None]]}
    query = {"filters": filters, "fields": ["name"]}
    if limit is not None:
        query["limit"] = limit
    donors = frappe.get_all("Donor", **query)
    created_or_linked = 0
    failed = 0
    for row in donors:
        try:
            get_or_create_customer_for_donor(row.name)
            created_or_linked += 1
        except Exception:
            failed += 1
            frappe.log_error(
                frappe.get_traceback(), _("Donor customer backfill failed")
            )
    return {"processed": len(donors), "linked": created_or_linked, "failed": failed}


def _customers_for_email(email: str | None) -> list[str]:
    email = _normalize_email(email)
    if not email:
        return []

    customers = []
    seen = set()
    if frappe.db.exists("DocType", "Member") and frappe.get_meta("Member").has_field(
        "customer"
    ):
        members = frappe.get_all(
            "Member",
            filters={"email_id": email},
            fields=["customer"],
            order_by="modified desc",
        )
        for member in members:
            if member.customer and frappe.db.exists("Customer", member.customer):
                customers.append(member.customer)
                seen.add(member.customer)

    if frappe.db.exists("DocType", "Customer") and frappe.get_meta(
        "Customer"
    ).has_field("email_id"):
        for row in frappe.get_all(
            "Customer",
            filters={"email_id": email},
            fields=["name"],
            order_by="modified desc",
        ):
            if row.name not in seen:
                customers.append(row.name)
                seen.add(row.name)
    return customers


def _customer_for_email(email: str | None) -> str | None:
    customers = _customers_for_email(email)
    return customers[0] if customers else None


def _normalize_email(email: str | None, *, validate: bool = False) -> str | None:
    value = cstr(email).strip().lower()
    if value and validate:
        from frappe.utils import validate_email_address

        validate_email_address(value, True)
    return value or None


def _legacy_donor_email(donor) -> str | None:
    if not donor:
        return None

    value = None
    if not isinstance(donor, str):
        value = donor.get("email")
        donor_name = donor.name
    else:
        donor_name = donor
    if not value and donor_name and frappe.db.has_column("Donor", "email"):
        value = frappe.db.get_value("Donor", donor_name, "email")
    return _normalize_email(value)


def _legacy_donor_name_for_email(email: str) -> str | None:
    if not frappe.db.has_column("Donor", "email"):
        return None
    return frappe.db.get_value(
        "Donor", {"email": email}, "name", order_by="modified desc"
    )


def _create_customer_for_donor(donor) -> str:
    customer = frappe.new_doc("Customer")
    customer.customer_name = donor.donor_name
    customer.customer_type = "Individual"
    customer.customer_group = _default_customer_group()
    customer.territory = _default_territory()
    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)
    return customer.name


def _link_contact_and_address_to_customer(
    donor, customer: str, email: str | None = None
) -> None:
    email = _normalize_email(email) or _legacy_donor_email(donor)
    contact_name = _contact_for_donor(donor, email=email, customer=customer)
    updates = {}
    if email and frappe.db.get_value("Customer", customer, "email_id") != email:
        updates["email_id"] = email
    if contact_name:
        _ensure_contact_link_row(contact_name, "Customer", customer)
        if (
            frappe.db.get_value("Customer", customer, "customer_primary_contact")
            != contact_name
        ):
            updates["customer_primary_contact"] = contact_name
        frappe.db.set_value(
            "Contact", contact_name, "is_primary_contact", 1, update_modified=False
        )
    if updates:
        frappe.db.set_value("Customer", customer, updates, update_modified=False)
    _link_donor_address_to_customer(donor.name, customer)


def _contact_for_donor(
    donor, email: str | None = None, customer: str | None = None
) -> str | None:
    contact_name = frappe.db.get_value(
        "Dynamic Link",
        {"parenttype": "Contact", "link_doctype": "Donor", "link_name": donor.name},
        "parent",
        order_by="idx asc",
    )
    if contact_name:
        return contact_name

    email = _normalize_email(email) or _legacy_donor_email(donor)
    if customer:
        contact_name = frappe.db.get_value(
            "Customer", customer, "customer_primary_contact"
        )
        if not contact_name:
            contact_name = frappe.db.get_value(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "link_doctype": "Customer",
                    "link_name": customer,
                },
                "parent",
                order_by="idx asc",
            )
        if contact_name:
            _ensure_contact_link_row(contact_name, "Donor", donor.name)
            return contact_name

    if not email:
        return None

    first_name, last_name = _split_person_name(donor.donor_name)
    if resolve_or_create_contact_from_external_signup and not customer:
        contact = resolve_or_create_contact_from_external_signup(
            email=email,
            first_name=first_name,
            last_name=last_name,
            full_name=donor.donor_name,
            links=[("Donor", donor.name)],
            source_doctype="Donor",
            source_name=donor.name,
        )
        return contact.name

    return _create_contact_for_donor(donor, first_name, last_name, email)


def _create_contact_for_donor(
    donor, first_name: str, last_name: str, email: str
) -> str | None:
    try:
        frappe.db.savepoint("donor_contact_creation")
        contact = frappe.new_doc("Contact")
        contact.first_name = first_name or donor.donor_name
        contact.last_name = last_name
        contact.add_email(email, is_primary=1)
        contact.insert(ignore_permissions=True)
        contact.append("links", {"link_doctype": "Donor", "link_name": donor.name})
        contact.save(ignore_permissions=True)
        return contact.name
    except frappe.DuplicateEntryError:
        contact_name = _existing_contact_for_email(email)
        if contact_name:
            _ensure_contact_link_row(contact_name, "Donor", donor.name)
        return contact_name
    except Exception:
        frappe.db.rollback(save_point="donor_contact_creation")
        frappe.log_error(frappe.get_traceback(), _("Donor Contact Creation Failed"))
        return None


def _existing_contact_for_email(email: str | None) -> str | None:
    if not email:
        return None
    return frappe.db.get_value(
        "Contact Email",
        {"email_id": cstr(email).strip().lower()},
        "parent",
        order_by="idx asc",
    )


def _ensure_contact_link_row(
    contact_name: str, link_doctype: str, link_name: str
) -> None:
    filters = {
        "parenttype": "Contact",
        "parent": contact_name,
        "link_doctype": link_doctype,
        "link_name": link_name,
    }
    if frappe.db.exists("Dynamic Link", filters):
        return
    existing_idx = frappe.get_all(
        "Dynamic Link",
        filters={"parenttype": "Contact", "parent": contact_name},
        pluck="idx",
        order_by="idx desc",
        limit=1,
    )
    frappe.get_doc(
        {
            "doctype": "Dynamic Link",
            "parenttype": "Contact",
            "parent": contact_name,
            "parentfield": "links",
            "idx": (existing_idx[0] if existing_idx else 0) + 1,
            "link_doctype": link_doctype,
            "link_name": link_name,
        }
    ).insert(ignore_permissions=True)


def _link_donor_address_to_customer(donor_name: str, customer: str) -> None:
    address_name = frappe.db.get_value(
        "Dynamic Link",
        {"parenttype": "Address", "link_doctype": "Donor", "link_name": donor_name},
        "parent",
        order_by="idx asc",
    )
    if not address_name:
        return
    if not frappe.db.exists(
        "Dynamic Link",
        {
            "parenttype": "Address",
            "parent": address_name,
            "link_doctype": "Customer",
            "link_name": customer,
        },
    ):
        address = frappe.get_doc("Address", address_name)
        address.append("links", {"link_doctype": "Customer", "link_name": customer})
        address.save(ignore_permissions=True)
    if frappe.get_meta("Customer").has_field("customer_primary_address"):
        frappe.db.set_value(
            "Customer",
            customer,
            "customer_primary_address",
            address_name,
            update_modified=False,
        )


def _split_person_name(fullname: str | None) -> tuple[str, str]:
    parts = cstr(fullname).strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _default_customer_group() -> str | None:
    for customer_group in ("Individual", "All Customer Groups"):
        if frappe.db.exists("Customer Group", customer_group):
            return customer_group
    return frappe.db.get_value(
        "Customer Group", {"is_group": 0}, "name", order_by="name asc"
    )


def _default_territory() -> str | None:
    for territory in ("Switzerland", "All Territories"):
        if frappe.db.exists("Territory", territory):
            return territory
    return frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
