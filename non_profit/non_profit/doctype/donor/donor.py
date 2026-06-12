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

from non_profit.non_profit.utils import split_person_name as _split_person_name


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
		frappe.msgprint(_("Customer {0} has been created successfully.").format(self.customer))


@frappe.whitelist(methods=["POST"])
def create_donor_from_identity(
	contact: str | None = None,
	customer: str | None = None,
	donor_type: str | None = None,
) -> dict[str, str | None]:
	contact = cstr(contact).strip()
	customer = cstr(customer).strip()
	if not contact and not customer:
		frappe.throw(_("Select a Contact or a Customer."))
	frappe.has_permission("Donor", "create", throw=True)
	if contact:
		_check_identity_doc_permission("Contact", contact, "write")
	if customer:
		_check_identity_doc_permission("Customer", customer, "write")

	if contact and customer:
		donor = get_or_create_donor_for_contact(
			contact,
			customer=customer,
			donor_type=donor_type,
		)
	elif contact:
		donor = get_or_create_donor_for_contact(contact, donor_type=donor_type)
	else:
		donor = get_or_create_donor_for_customer(customer, donor_type=donor_type)

	return {
		"donor": donor.name,
		"customer": donor.get("customer"),
		"contact": contact or _contact_for_donor(donor, customer=donor.get("customer")),
	}


def _check_identity_doc_permission(doctype: str, name: str, ptype: str = "read") -> None:
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	if ptype != "read":
		doc.check_permission(ptype)


def get_or_create_donor_for_customer(
	customer: str,
	donor_type: str | None = None,
	*,
	ignore_permissions: bool = False,
):
	if not customer:
		frappe.throw(_("Customer is required to create a Donor"))
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} does not exist").format(frappe.bold(customer)))
	if not ignore_permissions:
		_check_identity_doc_permission("Customer", customer, "write")

	existing_donor = frappe.db.exists("Donor", {"customer": customer})
	if existing_donor:
		donor = frappe.get_doc("Donor", existing_donor)
		if not ignore_permissions:
			donor.check_permission("read")
		return donor
	if not ignore_permissions:
		frappe.has_permission("Donor", "create", throw=True)

	donor = frappe.new_doc("Donor")
	donor.donor_type = _resolve_donor_type(donor_type)
	donor.donor_name = _customer_display_name(customer)
	donor.customer = customer
	donor.insert(ignore_permissions=ignore_permissions)
	_link_contact_and_address_to_customer(donor, customer)
	return donor


def get_or_create_donor_for_contact(
	contact: str,
	donor_type: str | None = None,
	*,
	customer: str | None = None,
	ignore_permissions: bool = False,
):
	if not contact:
		frappe.throw(_("Contact is required to create a Donor"))
	if not frappe.db.exists("Contact", contact):
		frappe.throw(_("Contact {0} does not exist").format(frappe.bold(contact)))
	if customer and not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} does not exist").format(frappe.bold(customer)))
	if not ignore_permissions:
		_check_identity_doc_permission("Contact", contact, "write")
		if customer:
			_check_identity_doc_permission("Customer", customer, "write")

	linked_donor = _donor_linked_to_contact(contact)
	if linked_donor:
		if customer:
			donor_for_customer = frappe.db.exists("Donor", {"customer": customer})
			if donor_for_customer and donor_for_customer != linked_donor:
				frappe.throw(
					_("Contact is already linked to another Donor."),
					frappe.ValidationError,
				)
		donor = frappe.get_doc("Donor", linked_donor)
		if not ignore_permissions:
			donor.check_permission("write" if customer and donor.get("customer") != customer else "read")
		if customer and donor.get("customer") != customer:
			frappe.db.set_value("Donor", donor.name, "customer", customer, update_modified=False)
			donor.customer = customer
		if customer:
			_link_contact_and_address_to_customer(donor, customer, email=get_contact_email(contact))
		return donor

	contact_doc = frappe.get_doc("Contact", contact)
	email = get_contact_email(contact_doc)
	if customer:
		existing_donor = frappe.db.exists("Donor", {"customer": customer})
		if existing_donor:
			ensure_contact_link(contact, "Donor", existing_donor, ignore_permissions=ignore_permissions)
			donor = frappe.get_doc("Donor", existing_donor)
			if not ignore_permissions:
				donor.check_permission("read")
			_link_contact_and_address_to_customer(donor, customer, email=email)
			return donor
	if email:
		existing_donor = find_donor_by_email(email)
		if existing_donor:
			ensure_contact_link(contact, "Donor", existing_donor, ignore_permissions=ignore_permissions)
			donor = frappe.get_doc("Donor", existing_donor)
			if not ignore_permissions:
				donor.check_permission("write" if customer and donor.get("customer") != customer else "read")
			if customer and donor.get("customer") != customer:
				frappe.db.set_value("Donor", donor.name, "customer", customer, update_modified=False)
				donor.customer = customer
			if donor.get("customer"):
				_link_contact_and_address_to_customer(donor, donor.customer, email=email)
			return donor

	donor = frappe.new_doc("Donor")
	if not ignore_permissions:
		frappe.has_permission("Donor", "create", throw=True)
	donor.donor_type = _resolve_donor_type(donor_type)
	donor.donor_name = get_contact_display_name(contact_doc)
	if customer:
		donor.customer = customer
	donor.insert(ignore_permissions=ignore_permissions)
	ensure_contact_link(contact, "Donor", donor.name, ignore_permissions=ignore_permissions)
	if customer:
		_link_contact_and_address_to_customer(donor, customer, email=email)
	return donor


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
		frappe.db.set_value("Donor", donor.name, "customer", customer, update_modified=False)
		donor.customer = customer

	_link_contact_and_address_to_customer(donor, customer, email=email)
	return customer


def find_donor_by_email(email: str | None) -> str | None:
	email = _normalize_email(email, validate=True)
	if not email:
		return None

	for customer in _customers_for_email(email):
		donor = frappe.db.get_value("Donor", {"customer": customer}, "name", order_by="modified desc")
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

	contact = _contact_linked_to("Donor", donor_name)
	if contact:
		email = get_contact_email(contact)
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
			frappe.log_error(frappe.get_traceback(), _("Donor customer backfill failed"))
	return {"processed": len(donors), "linked": created_or_linked, "failed": failed}


def _customers_for_email(email: str | None) -> list[str]:
	email = _normalize_email(email)
	if not email:
		return []

	customers = []
	seen = set()
	if frappe.db.exists("DocType", "Member") and frappe.get_meta("Member").has_field("customer"):
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

	if frappe.db.exists("DocType", "Customer") and frappe.get_meta("Customer").has_field("email_id"):
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
	return frappe.db.get_value("Donor", {"email": email}, "name", order_by="modified desc")


def _create_customer_for_donor(donor) -> str:
	customer = frappe.new_doc("Customer")
	customer.customer_name = donor.donor_name
	customer.customer_type = "Individual"
	customer.customer_group = _default_customer_group()
	customer.territory = _default_territory()
	customer.flags.ignore_mandatory = True
	customer.insert(ignore_permissions=True)
	return customer.name


def _link_contact_and_address_to_customer(donor, customer: str, email: str | None = None) -> None:
	email = _normalize_email(email) or _legacy_donor_email(donor)
	contact_name = _contact_for_donor(donor, email=email, customer=customer)
	updates = {}
	if email and frappe.db.get_value("Customer", customer, "email_id") != email:
		updates["email_id"] = email
	if contact_name:
		_ensure_contact_link_row(contact_name, "Customer", customer)
		if frappe.db.get_value("Customer", customer, "customer_primary_contact") != contact_name:
			updates["customer_primary_contact"] = contact_name
		frappe.db.set_value("Contact", contact_name, "is_primary_contact", 1, update_modified=False)
	if updates:
		frappe.db.set_value("Customer", customer, updates, update_modified=False)
	_link_donor_address_to_customer(donor.name, customer)


def _contact_for_donor(donor, email: str | None = None, customer: str | None = None) -> str | None:
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
		contact_name = frappe.db.get_value("Customer", customer, "customer_primary_contact")
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
			ensure_contact_link(contact_name, "Donor", donor.name)
			return contact_name

	if not email:
		return None

	first_name, last_name = _split_person_name(donor.donor_name)
	if resolve_or_create_contact_from_external_signup:
		links = [("Donor", donor.name)]
		if customer:
			links.append(("Customer", customer))
		contact = resolve_or_create_contact_from_external_signup(
			email=email,
			first_name=first_name,
			last_name=last_name,
			full_name=donor.donor_name,
			links=links,
			source_doctype="Donor",
			source_name=donor.name,
		)
		return contact.name

	return _create_contact_for_donor(donor, first_name, last_name, email)


def _create_contact_for_donor(donor, first_name: str, last_name: str, email: str) -> str | None:
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


def ensure_contact_link(
	contact_name: str,
	link_doctype: str,
	link_name: str,
	*,
	ignore_permissions: bool = True,
) -> None:
	_ensure_contact_link_row(
		contact_name,
		link_doctype,
		link_name,
		ignore_permissions=ignore_permissions,
	)


def _ensure_contact_link_row(
	contact_name: str,
	link_doctype: str,
	link_name: str,
	*,
	ignore_permissions: bool = True,
) -> None:
	filters = {
		"parenttype": "Contact",
		"parent": contact_name,
		"link_doctype": link_doctype,
		"link_name": link_name,
	}
	if frappe.db.exists("Dynamic Link", filters):
		return
	contact = frappe.get_doc("Contact", contact_name)
	contact.append("links", {"link_doctype": link_doctype, "link_name": link_name})
	contact.save(ignore_permissions=ignore_permissions)


def get_contact_email(contact) -> str | None:
	if isinstance(contact, str):
		contact = frappe.get_doc("Contact", contact)
	if contact.get("email_id"):
		return _normalize_email(contact.email_id)
	emails = sorted(
		contact.get("email_ids") or [],
		key=lambda row: (0 if row.get("is_primary") else 1, row.get("idx") or 0),
	)
	return _normalize_email(emails[0].email_id) if emails else None


def get_contact_display_name(contact_doc) -> str:
	full_name = cstr(contact_doc.get("full_name")).strip()
	if full_name:
		return full_name
	name_parts = [contact_doc.get("first_name"), contact_doc.get("last_name")]
	return " ".join(part for part in name_parts if cstr(part).strip()).strip() or contact_doc.name


def _donor_linked_to_contact(contact: str) -> str | None:
	donor = frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "parent": contact, "link_doctype": "Donor"},
		"link_name",
		order_by="idx asc",
	)
	return donor if donor and frappe.db.exists("Donor", donor) else None


def _contact_linked_to(link_doctype: str, link_name: str) -> str | None:
	return frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "link_doctype": link_doctype, "link_name": link_name},
		"parent",
		order_by="idx asc",
	)


def _customer_display_name(customer: str) -> str:
	customer_doc = frappe.get_doc("Customer", customer)
	name = customer_doc.customer_name or customer
	additional = cstr(customer_doc.get("name_additional")).strip()
	return f"{name} - {additional}" if additional else name


def _resolve_donor_type(donor_type: str | None = None) -> str:
	donor_type = cstr(donor_type).strip()
	if donor_type and frappe.db.exists("Donor Type", donor_type):
		return donor_type
	settings_type = frappe.db.get_single_value("Non Profit Settings", "default_donor_type")
	if settings_type and frappe.db.exists("Donor Type", settings_type):
		return settings_type
	existing = frappe.db.get_value("Donor Type", {}, "name", order_by="name asc")
	if existing:
		return existing
	doc = frappe.get_doc({"doctype": "Donor Type", "donor_type": "Individual"})
	doc.insert(ignore_permissions=True)
	return doc.name


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


def _default_customer_group() -> str | None:
	for customer_group in ("Individual", "All Customer Groups"):
		if frappe.db.exists("Customer Group", customer_group):
			return customer_group
	return frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name asc")


def _default_territory() -> str | None:
	for territory in ("Switzerland", "All Territories"):
		if frappe.db.exists("Territory", territory):
			return territory
	return frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
