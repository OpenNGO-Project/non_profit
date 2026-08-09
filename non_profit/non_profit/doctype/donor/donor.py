# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cstr

from non_profit.non_profit.integration_hooks import CONTACT_RESOLUTION, first_provider
from non_profit.non_profit.utils import (
	ensure_canonical_contact_available,
	ensure_person_contact,
	role_uses_canonical_person,
	validate_person_role_contact_change,
)
from non_profit.non_profit.utils import split_person_name as _split_person_name


class Donor(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self) -> None:
		from non_profit.non_profit.doctype.household.household import get_current_household

		validate_person_role_contact_change(self)
		if self.contact:
			if self.subject_type and self.subject_type != "Individual":
				frappe.throw(_("A Donor with a canonical Contact must represent an individual."))
			self.subject_type = "Individual"
			ensure_person_contact(self.contact)
		if self.subject_type == "Household" and self.subject_household:
			self.household = self.subject_household
		else:
			self.household = get_current_household(self.contact) if self.contact else None

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
		repair_subject_type = (
			frappe.db.get_value("Customer", customer, "customer_type") == "Company"
			and not donor.subject_type
			and not donor.contact
		)
		if not ignore_permissions:
			donor.check_permission("write" if repair_subject_type else "read")
		if repair_subject_type:
			frappe.db.set_value("Donor", donor.name, "subject_type", "Organization", update_modified=False)
			donor.subject_type = "Organization"
		return donor
	if not ignore_permissions:
		frappe.has_permission("Donor", "create", throw=True)

	donor = frappe.new_doc("Donor")
	donor.donor_type = _resolve_donor_type(donor_type)
	donor.donor_name = _customer_display_name(customer)
	donor.customer = customer
	if frappe.db.get_value("Customer", customer, "customer_type") == "Company":
		donor.subject_type = "Organization"
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
		ensure_contact_link(contact, "Donor", linked_donor, ignore_permissions=ignore_permissions)
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
		existing_donor = next(
			(donor for donor in find_donors_by_email(email) if role_uses_canonical_person("Donor", donor)),
			None,
		)
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
	donor.subject_type = "Individual"
	donor.contact = contact
	if customer:
		donor.customer = customer
	donor.insert(ignore_permissions=ignore_permissions)
	ensure_contact_link(contact, "Donor", donor.name, ignore_permissions=ignore_permissions)
	if customer:
		_link_contact_and_address_to_customer(donor, customer, email=email)
	return donor


def get_or_create_donor_for_household(
	household: str,
	donor_type: str | None = None,
	*,
	ignore_permissions: bool = False,
):
	"""Resolve one Household-subject Donor while holding the Household row lock."""
	household = cstr(household).strip()
	if not household:
		frappe.throw(_("Household is required to create a Donor"))

	household_row = frappe.db.get_value(
		"Household",
		household,
		["name", "household_name"],
		as_dict=True,
		for_update=True,
	)
	if not household_row:
		frappe.throw(
			_("Household {0} does not exist").format(frappe.bold(household)),
			frappe.DoesNotExistError,
		)
	if not ignore_permissions:
		household_doc = frappe.get_doc("Household", household)
		household_doc.check_permission("write")

	donor_table = frappe.qb.DocType("Donor")
	donor_names = (
		frappe.qb.from_(donor_table)
		.select(donor_table.name)
		.where(donor_table.subject_household == household)
		.where(
			(donor_table.subject_type == "Household")
			| donor_table.subject_type.isnull()
			| (donor_table.subject_type == "")
		)
		.orderby(donor_table.name)
		.limit(2)
	).run(pluck=True)
	if len(donor_names) > 1:
		frappe.throw(
			_("Household {0} has more than one active Household Donor. Staff review is required.").format(
				frappe.bold(household)
			)
		)
	if donor_names:
		donor = frappe.get_doc("Donor", donor_names[0])
		if not ignore_permissions:
			donor.check_permission("read")
		return donor

	if not ignore_permissions:
		frappe.has_permission("Donor", "create", throw=True)
	donor = frappe.new_doc("Donor")
	donor.donor_name = household_row.household_name
	donor.donor_type = _resolve_donor_type(donor_type)
	donor.subject_type = "Household"
	donor.subject_household = household
	donor.insert(ignore_permissions=ignore_permissions)
	return donor


def get_or_create_customer_for_donor(
	donor,
	email: str | None = None,
	*,
	customer_values_provider=None,
) -> str:
	if isinstance(donor, str):
		donor = frappe.get_doc("Donor", donor)
	email = _normalize_email(email, validate=True) or _legacy_donor_email(donor)

	if donor.get("customer") and frappe.db.exists("Customer", donor.customer):
		_link_contact_and_address_to_customer(donor, donor.customer, email=email)
		return donor.customer

	customer = _customer_for_email(email)
	if not customer:
		customer = _create_customer_for_donor(donor, values_provider=customer_values_provider)

	if donor.get("customer") != customer:
		frappe.db.set_value("Donor", donor.name, "customer", customer, update_modified=False)
		donor.customer = customer

	_link_contact_and_address_to_customer(donor, customer, email=email)
	return customer


def find_donor_by_email(email: str | None) -> str | None:
	donors = find_donors_by_email(email)
	return donors[0] if donors else None


def find_donors_by_email(email: str | None) -> list[str]:
	donors, _customers = find_donor_customer_candidates(email)
	return donors


def find_donor_customer_candidates(email: str | None) -> tuple[list[str], list[str]]:
	"""Return every Donor and Customer resolving to one normalized email."""
	email = _normalize_email(email, validate=True)
	if not email:
		return [], []

	customers = _customers_for_email(email)
	donor_rows = (
		frappe.get_all(
			"Donor",
			filters={"customer": ["in", customers]},
			fields=["name", "customer"],
			order_by="modified desc",
		)
		if customers
		else []
	)
	donors_by_customer = {}
	for row in donor_rows:
		donors_by_customer.setdefault(row.customer, []).append(row.name)
	donors = [donor for customer in customers for donor in donors_by_customer.get(customer, [])]

	for canonical_donor in _canonical_contact_donor_names_for_email(email):
		if canonical_donor not in donors:
			donors.append(canonical_donor)

	for legacy_donor in _legacy_donor_names_for_email(email):
		if legacy_donor not in donors:
			donors.append(legacy_donor)
	return donors, customers


def donor_customer_share_identity(donor_name: str, customer_name: str) -> bool:
	"""Whether existing links prove that a Donor and Customer are one identity."""
	donor = frappe.db.get_value("Donor", donor_name, ["customer", "contact"], as_dict=True) or {}
	if donor.get("customer") == customer_name:
		return True

	contact = cstr(donor.get("contact")).strip()
	if not contact:
		return False

	customer_fields = ["customer_primary_contact"]
	customer_meta = frappe.get_meta("Customer")
	if customer_meta.has_field("npo_subject_type"):
		customer_fields.append("npo_subject_type")
	if customer_meta.has_field("npo_contact"):
		customer_fields.append("npo_contact")
	customer = frappe.db.get_value("Customer", customer_name, customer_fields, as_dict=True) or {}
	if cstr(customer.get("npo_subject_type")).strip() != "Person":
		return False
	if contact in {
		cstr(customer.get("customer_primary_contact")).strip(),
		cstr(customer.get("npo_contact")).strip(),
	}:
		return True

	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{
				"parenttype": "Contact",
				"parent": contact,
				"link_doctype": "Customer",
				"link_name": customer_name,
			},
		)
	)


def get_donor_email(donor) -> str | None:
	if not donor:
		return None

	if isinstance(donor, str):
		values = frappe.db.get_value("Donor", donor, ["customer", "contact"], as_dict=True) or {}
		customer = values.get("customer")
		canonical_contact = values.get("contact")
		donor_name = donor
	else:
		customer = donor.get("customer")
		canonical_contact = donor.get("contact")
		donor_name = donor.name

	if canonical_contact:
		email = get_contact_email(canonical_contact)
		if email:
			return email
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
			frappe.log_error(title=_("Donor customer backfill failed"), message=frappe.get_traceback())
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
			if (
				member.customer
				and member.customer not in seen
				and frappe.db.exists("Customer", member.customer)
			):
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


def _canonical_contact_donor_names_for_email(email: str) -> list[str]:
	contact_meta = frappe.get_meta("Contact")
	fields = ["name"]
	if contact_meta.has_field("npo_identity_kind"):
		fields.append("npo_identity_kind")
	contact_rows = frappe.get_all(
		"Contact",
		filters={"email_id": email},
		fields=fields,
		order_by="name asc",
	)
	contact_names = [
		row.name
		for row in contact_rows
		if not contact_meta.has_field("npo_identity_kind")
		or cstr(row.npo_identity_kind).strip() in ("", "Person")
	]
	if not contact_names:
		return []
	return frappe.get_all(
		"Donor",
		filters={"contact": ["in", contact_names]},
		pluck="name",
		order_by="modified desc, name asc",
	)


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


def _legacy_donor_names_for_email(email: str) -> list[str]:
	if not frappe.db.has_column("Donor", "email"):
		return []
	return frappe.get_all(
		"Donor",
		filters={"email": email},
		pluck="name",
		order_by="modified desc",
	)


def _create_customer_for_donor(donor, *, values_provider=None) -> str:
	values = {
		"doctype": "Customer",
		"customer_name": donor.donor_name,
		"customer_type": "Company" if donor.get("subject_type") == "Organization" else "Individual",
		"customer_group": _default_customer_group(),
		"territory": _default_territory(),
	}
	if values_provider and (provided := values_provider(dict(values))):
		values.update(provided)
	customer = frappe.get_doc(values)
	customer.flags.ignore_mandatory = True
	customer.insert(ignore_permissions=True)
	return customer.name


def _link_contact_and_address_to_customer(donor, customer: str, email: str | None = None) -> None:
	if (
		frappe.db.get_value("Customer", customer, "customer_type") == "Company"
		and not donor.get("subject_type")
		and not donor.get("contact")
	):
		frappe.db.set_value("Donor", donor.name, "subject_type", "Organization", update_modified=False)
		donor.subject_type = "Organization"
	email = _normalize_email(email) or _legacy_donor_email(donor)
	contact_name = _contact_for_donor(donor, email=email, customer=customer)
	updates = {}
	if email and frappe.db.get_value("Customer", customer, "email_id") != email:
		updates["email_id"] = email
	if contact_name:
		if donor.get("subject_type") in (None, "", "Individual"):
			current_household = ensure_contact_link(contact_name, "Donor", donor.name)
			donor.subject_type = "Individual"
			donor.contact = contact_name
			donor.household = current_household
		else:
			_ensure_contact_link_row(contact_name, "Donor", donor.name)
		_ensure_contact_link_row(contact_name, "Customer", customer)
		if frappe.db.get_value("Customer", customer, "customer_primary_contact") != contact_name:
			updates["customer_primary_contact"] = contact_name
		frappe.db.set_value("Contact", contact_name, "is_primary_contact", 1, update_modified=False)
	if updates:
		frappe.db.set_value("Customer", customer, updates, update_modified=False)
	_link_donor_address_to_customer(donor.name, customer)


def _contact_for_donor(donor, email: str | None = None, customer: str | None = None) -> str | None:
	if donor.get("contact") and frappe.db.exists("Contact", donor.contact):
		return donor.contact
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
			if donor.get("subject_type") in (None, "", "Individual"):
				ensure_contact_link(contact_name, "Donor", donor.name)
			else:
				_ensure_contact_link_row(contact_name, "Donor", donor.name)
			return contact_name

	if not email:
		return None

	first_name, last_name = _split_person_name(donor.donor_name)
	if resolve_contact := first_provider(CONTACT_RESOLUTION):
		links = [("Donor", donor.name)]
		if customer:
			links.append(("Customer", customer))
		contact = resolve_contact(
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
		frappe.log_error(title=_("Donor Contact Creation Failed"), message=frappe.get_traceback())
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
) -> str | None:
	contact = frappe.get_doc("Contact", contact_name)
	if not ignore_permissions:
		contact.check_permission("write")
	current_household = None
	if link_doctype == "Donor" and frappe.db.exists("Donor", link_name):
		subject_type = frappe.db.get_value("Donor", link_name, "subject_type")
		if subject_type and subject_type != "Individual":
			frappe.throw(
				_("Donor {0} does not represent an individual Contact.").format(frappe.bold(link_name))
			)
		ensure_canonical_contact_available("Donor", link_name, contact_name)
		# The canonical-contact check locks the Donor in the shared identity lock
		# order; capture the former projection from that current row.
		previous_household = frappe.db.get_value("Donor", link_name, "household")
		ensure_person_contact(contact_name)
		frappe.db.set_value(
			"Donor",
			link_name,
			{"subject_type": "Individual", "contact": contact_name},
			update_modified=False,
		)
		from non_profit.non_profit.doctype.household.household import sync_contact_role_households

		current_household = sync_contact_role_households(contact_name)
		from non_profit.non_profit.household_giving import recompute_household_giving

		for household in sorted({previous_household, current_household} - {None, ""}):
			recompute_household_giving(household)
	_ensure_contact_link_row(
		contact_name,
		link_doctype,
		link_name,
		ignore_permissions=ignore_permissions,
	)
	return current_household


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
	if donor := frappe.db.get_value("Donor", {"contact": contact}, "name"):
		return donor
	donors = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "parent": contact, "link_doctype": "Donor"},
		pluck="link_name",
		order_by="idx asc",
	)
	return next(
		(
			donor
			for donor in donors
			if frappe.db.exists("Donor", donor) and role_uses_canonical_person("Donor", donor)
		),
		None,
	)


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
	address_names = sorted(
		set(
			frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Address", "link_doctype": "Donor", "link_name": donor_name},
				pluck="parent",
				order_by="parent asc",
			)
		)
	)
	if not address_names:
		return

	existing_primary = frappe.db.get_value("Customer", customer, "customer_primary_address")
	addresses = [frappe.get_doc("Address", name, for_update=True) for name in address_names]
	for address in addresses:
		if any(
			row.link_doctype == "Customer" and row.link_name == customer for row in address.get("links") or []
		):
			continue
		address.append("links", {"link_doctype": "Customer", "link_name": customer})
		address.save(ignore_permissions=True)

	if not frappe.get_meta("Customer").has_field("customer_primary_address"):
		return
	if existing_primary:
		if frappe.db.get_value("Customer", customer, "customer_primary_address") != existing_primary:
			frappe.db.set_value(
				"Customer",
				customer,
				"customer_primary_address",
				existing_primary,
				update_modified=False,
			)
		return

	active_addresses = [address for address in addresses if not address.get("disabled")]
	primary_addresses = [address.name for address in active_addresses if address.get("is_primary_address")]
	selected_primary = None
	if len(primary_addresses) == 1:
		selected_primary = primary_addresses[0]
	elif not primary_addresses and len(active_addresses) == 1:
		selected_primary = active_addresses[0].name
	if frappe.db.get_value("Customer", customer, "customer_primary_address") != selected_primary:
		frappe.db.set_value(
			"Customer",
			customer,
			"customer_primary_address",
			selected_primary,
			update_modified=False,
		)


def _default_customer_group() -> str:
	configured = frappe.db.get_single_value("Selling Settings", "customer_group")
	for customer_group in (configured, "Individual"):
		if customer_group and frappe.db.get_value("Customer Group", customer_group, "is_group") == 0:
			return customer_group
	if customer_group := frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name asc"):
		return customer_group
	frappe.throw(
		_("Configure a non-group Default Customer Group in Selling Settings before creating Customers."),
		frappe.ValidationError,
	)


def _default_territory() -> str | None:
	for territory in ("Switzerland", "All Territories"):
		if frappe.db.exists("Territory", territory):
			return territory
	return frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
