from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, getdate, validate_email_address

from non_profit.non_profit.identity_lock import acquire_identity_lock
from non_profit.non_profit.utils import ensure_person_contact, role_uses_canonical_person

MUTATED_IDENTITY_DOCTYPES = ("Contact", "Address", "Customer", "Member", "Membership")
ORGANIZATION_CUSTOMER_TYPES = {"Company", "Partnership"}


def create_guided_membership(
	*,
	member_kind: str,
	membership_type: str,
	existing_contact: str | None = None,
	existing_address: str | None = None,
	from_date: str | None = None,
	first_name: str | None = None,
	last_name: str | None = None,
	email: str | None = None,
	phone: str | None = None,
	organization_name: str | None = None,
	organization_contact_first_name: str | None = None,
	organization_contact_last_name: str | None = None,
	organization_contact_email: str | None = None,
	organization_contact_phone: str | None = None,
	address_line1: str | None = None,
	postal_code: str | None = None,
	city: str | None = None,
	country: str | None = None,
) -> dict[str, str | None]:
	"""Create a complete Desk membership identity without using the guest signup flow."""

	if "good_connector" not in frappe.get_installed_apps():
		frappe.throw(_("Good Connector identity matching is required for guided Member creation."))
	member_kind = cstr(member_kind).strip()
	identity_locks = []
	if cstr(existing_contact).strip():
		identity_locks.append(("Contact", cstr(existing_contact).strip()))
	if cstr(existing_address).strip():
		identity_locks.append(("Address", cstr(existing_address).strip()))
	if member_kind == "Individual" and cstr(email).strip():
		identity_locks.append(("Individual", cstr(email).strip().lower()))
	elif member_kind == "Organization" and cstr(organization_name).strip():
		identity_locks.append(("Organization", cstr(organization_name).strip()))
		if cstr(organization_contact_email).strip():
			identity_locks.append(("Individual", cstr(organization_contact_email).strip().lower()))
	_acquire_identity_locks(identity_locks)
	_check_permissions()
	membership_type = cstr(membership_type).strip()
	if not membership_type:
		frappe.throw(_("Membership Type is required to create a Membership"))
	frappe.get_doc("Membership Type", membership_type, for_update=True).check_permission("read")
	start_date = getdate(_required(from_date, _("From Date")))
	savepoint = f"guided_member_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		if member_kind == "Individual":
			result = _create_individual(
				existing_contact=existing_contact,
				existing_address=existing_address,
				first_name=first_name,
				last_name=last_name,
				email=email,
				phone=phone,
				address_line1=address_line1,
				postal_code=postal_code,
				city=city,
				country=country,
			)
		elif member_kind == "Organization":
			result = _create_organization(
				existing_contact=existing_contact,
				existing_address=existing_address,
				organization_name=organization_name,
				contact_first_name=organization_contact_first_name,
				contact_last_name=organization_contact_last_name,
				contact_email=organization_contact_email,
				contact_phone=organization_contact_phone,
				address_line1=address_line1,
				postal_code=postal_code,
				city=city,
				country=country,
			)
		else:
			frappe.throw(_("Select Individual or Organization."))

		from non_profit.non_profit.doctype.member.member import get_or_create_membership_for_member

		membership = get_or_create_membership_for_member(
			result.member,
			membership_type=membership_type,
			from_date=start_date,
			membership_status="Current",
			keep_to_date_open=True,
			keep_from_date=True,
		)
		if membership.membership_status != "Current":
			frappe.throw(
				_(
					"An active non-Current Membership already exists for this identity. Staff review is required."
				)
			)
		return {
			"member": result.member,
			"membership": membership.name,
			"customer": result.customer,
			"contact": result.contact,
			"address": result.address,
			"membership_type": membership.membership_type,
		}
	except frappe.QueryDeadlockError:
		# MariaDB has already rolled back the whole transaction, including this savepoint.
		raise
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise


def _check_permissions() -> None:
	# The resolver may create or reuse each identity layer, so authorize both paths before any write.
	for doctype in MUTATED_IDENTITY_DOCTYPES:
		for permission_type in ("create", "read", "write"):
			frappe.has_permission(doctype, permission_type, throw=True)


def _create_individual(
	*,
	existing_contact: str | None,
	existing_address: str | None,
	first_name: str | None,
	last_name: str | None,
	email: str | None,
	phone: str | None,
	address_line1: str | None,
	postal_code: str | None,
	city: str | None,
	country: str | None,
) -> frappe._dict:
	contact = None
	if cstr(existing_contact).strip():
		contact, first_name, last_name, email, phone = _selected_person_contact(existing_contact)
	else:
		first_name = _required(first_name, _("First Name"))
		last_name = _required(last_name, _("Last Name"))
		email = _email(email, required=True)
		contact = _resolve_person_contact(first_name, last_name, email, phone)

	address_doc, address = _selected_address(existing_address, required=True)
	if not address_doc:
		address = _address_payload(
			address_line1=address_line1,
			postal_code=postal_code,
			city=city,
			country=country,
			required=True,
		)
	member = _member_for_person(contact.name, first_name, last_name, email)
	customer = _customer_for_person(member, contact.name, first_name, last_name, email)
	address_doc = _resolve_address(
		address,
		existing_address=address_doc,
		links=[("Contact", contact.name), ("Customer", customer), ("Member", member.name)],
		address_title=member.member_name,
		email=email,
		phone=phone,
	)
	return frappe._dict(
		member=member.name,
		customer=customer,
		contact=contact.name,
		address=address_doc.name if address_doc else None,
	)


def _create_organization(
	*,
	existing_contact: str | None,
	existing_address: str | None,
	organization_name: str | None,
	contact_first_name: str | None,
	contact_last_name: str | None,
	contact_email: str | None,
	contact_phone: str | None,
	address_line1: str | None,
	postal_code: str | None,
	city: str | None,
	country: str | None,
) -> frappe._dict:
	organization_name = " ".join(_required(organization_name, _("Organization Name")).split())
	contact = None
	if cstr(existing_contact).strip():
		contact, contact_first_name, contact_last_name, contact_email, contact_phone = (
			_selected_person_contact(existing_contact)
		)
	else:
		contact_values = [contact_first_name, contact_last_name, contact_email, contact_phone]
		if any(cstr(value).strip() for value in contact_values):
			contact_first_name = _required(contact_first_name, _("Contact Person First Name"))
			contact_last_name = _required(contact_last_name, _("Contact Person Last Name"))
			contact_email = _email(contact_email, required=True)
	if contact_email and not contact:
		contact = _resolve_person_contact(
			contact_first_name,
			contact_last_name,
			contact_email,
			contact_phone,
		)
	address_doc, address = _selected_address(existing_address, required=True)
	if not address_doc:
		address = _address_payload(
			address_line1=address_line1,
			postal_code=postal_code,
			city=city,
			country=country,
			required=False,
		)
	customer = _organization_customer(organization_name, address)
	member = _member_for_organization(customer, organization_name)

	if contact:
		_link_organization_contact(contact, customer, member.name)

	address_doc = _resolve_address(
		address,
		existing_address=address_doc,
		links=[("Customer", customer), ("Member", member.name)],
		address_title=organization_name,
		email=None,
		phone=None,
	)
	return frappe._dict(
		member=member.name,
		customer=customer,
		contact=contact.name if contact else None,
		address=address_doc.name if address_doc else None,
	)


def _selected_person_contact(contact_name: str):
	contact = frappe.get_doc("Contact", cstr(contact_name).strip(), for_update=True)
	contact.check_permission("read")
	contact.check_permission("write")
	ensure_person_contact(contact.name)
	first_name = _required(contact.first_name, _("First Name"))
	last_name = _required(contact.last_name, _("Last Name"))
	email = _email(contact.email_id, required=True)
	phone = cstr(contact.phone).strip() or None
	return contact, first_name, last_name, email, phone


def _selected_address(address_name: str | None, *, required: bool):
	address_name = cstr(address_name).strip()
	if not address_name:
		return None, None
	address = frappe.get_doc("Address", address_name, for_update=True)
	address.check_permission("read")
	address.check_permission("write")
	payload = _address_payload(
		address_line1=address.address_line1,
		postal_code=address.pincode,
		city=address.city,
		country=address.country,
		required=required,
	)
	return address, payload


def _resolve_person_contact(
	first_name: str,
	last_name: str,
	email: str,
	phone: str | None,
):
	try:
		from good_connector.identity_matching import resolve_or_create_contact_from_external_signup
	except ImportError:
		frappe.throw(_("Good Connector identity matching is required for guided Member creation."))

	contact_names = _contacts_for_email(email)
	contacts = {}
	for contact_name in contact_names:
		contact_doc = frappe.get_doc("Contact", contact_name, for_update=True)
		contact_doc.check_permission("read")
		contact_doc.check_permission("write")
		contacts[contact_name] = contact_doc
	exact_contacts = [
		contact_name
		for contact_name in contact_names
		if _same_text(contacts[contact_name].first_name, first_name)
		and _same_text(contacts[contact_name].last_name, last_name)
	]
	if len(exact_contacts) > 1:
		frappe.throw(_("More than one Contact has this exact name and email. Staff review is required."))
	if contact_names and not exact_contacts:
		frappe.throw(_("This email belongs to a different or ambiguous Contact. Staff review is required."))
	if exact_contacts:
		contact = contacts[exact_contacts[0]]
		ensure_person_contact(contact.name)
		phone = cstr(phone).strip()[:80]
		phone_key = _phone_key(phone)
		if phone_key and not any(_phone_key(row.phone) == phone_key for row in contact.phone_nos):
			contact.append(
				"phone_nos",
				{
					"phone": phone,
					"is_primary_phone": 0 if any(row.is_primary_phone for row in contact.phone_nos) else 1,
				},
			)
			contact.save()
		return contact

	contact = resolve_or_create_contact_from_external_signup(
		email=email,
		first_name=first_name,
		last_name=last_name,
		full_name=f"{first_name} {last_name}",
		phone=cstr(phone).strip() or None,
		source_doctype="Member",
		source_name=email,
	)
	ensure_person_contact(contact.name)
	return contact


def _member_for_person(contact: str, first_name: str, last_name: str, email: str):
	from non_profit.non_profit.doctype.member.member import _link_contact_to_member

	contact_members = _canonical_members_for_contact(contact)
	member_doctype = frappe.qb.DocType("Member")
	email_members = (
		frappe.qb.from_(member_doctype)
		.select(member_doctype.name)
		.where(member_doctype.email_id == email)
		.orderby(member_doctype.name)
		.for_update()
	).run(pluck=True)
	if len(contact_members) > 1:
		frappe.throw(_("This Contact is linked to more than one Member. Staff review is required."))
	member_name = contact_members[0] if contact_members else None
	if any(name != member_name for name in email_members):
		frappe.throw(_("This email is linked to a different or ambiguous Member. Staff review is required."))

	if member_name:
		member = frappe.get_doc("Member", member_name, for_update=True)
		member.check_permission("read")
		member.check_permission("write")
		if member.subject_type and member.subject_type != "Individual":
			frappe.throw(_("The resolved Member does not represent an individual. Staff review is required."))
		if member.email_id and member.email_id.strip().lower() != email:
			frappe.throw(_("The resolved Member has a different email. Staff review is required."))
		if not member.email_id:
			member.email_id = email
			member.save()
	else:
		member = frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": f"{first_name} {last_name}",
				"email_id": email,
				"subject_type": "Individual",
				"contact": contact,
			}
		).insert()
	_link_contact_to_member(contact, member.name)
	member.reload()
	return member


def _customer_for_person(member, contact: str, first_name: str, last_name: str, email: str) -> str:
	candidates = set()
	if member.customer and frappe.db.exists("Customer", member.customer):
		candidates.add(member.customer)
	customer_doctype = frappe.qb.DocType("Customer")
	candidates.update(
		(
			frappe.qb.from_(customer_doctype)
			.select(customer_doctype.name)
			.where(customer_doctype.customer_primary_contact == contact)
		).run(pluck=True)
	)
	dynamic_link = frappe.qb.DocType("Dynamic Link")
	candidates.update(
		(
			frappe.qb.from_(dynamic_link)
			.select(dynamic_link.link_name)
			.where(dynamic_link.parenttype == "Contact")
			.where(dynamic_link.parent == contact)
			.where(dynamic_link.link_doctype == "Customer")
		).run(pluck=True)
	)
	_lock_names("Customer", candidates)
	customers = {
		name: frappe.get_doc("Customer", name, for_update=True)
		for name in candidates
		if frappe.db.exists("Customer", name)
	}
	individual_candidates = {
		name for name, customer in customers.items() if customer.customer_type == "Individual"
	}
	if member.customer and member.customer not in individual_candidates:
		frappe.throw(
			_("This individual Member is linked to a non-individual Customer. Staff review is required.")
		)
	if len(individual_candidates) > 1:
		frappe.throw(
			_("This Contact is linked to more than one individual Customer. Staff review is required.")
		)

	if individual_candidates:
		customer = customers[next(iter(individual_candidates))]
		customer.check_permission("read")
		customer.check_permission("write")
	else:
		customer = _new_customer(f"{first_name} {last_name}", "Individual")

	_link_contact_to_customer(contact, customer, email=email, set_primary=True)
	if member.customer != customer.name:
		member.customer = customer.name
		member.save()
	return customer.name


def _organization_customer(organization_name: str, address: dict[str, str] | None) -> str:
	customer_doctype = frappe.qb.DocType("Customer")
	matching_customers = (
		frappe.qb.from_(customer_doctype)
		.select(customer_doctype.name, customer_doctype.customer_type)
		.where(customer_doctype.customer_name == organization_name)
		.orderby(customer_doctype.name)
		.for_update()
	).run(as_dict=True)
	if any(row.customer_type not in ORGANIZATION_CUSTOMER_TYPES for row in matching_customers):
		frappe.throw(
			_("A Customer with this organization name has a non-organization type. Staff review is required.")
		)
	candidates = [row.name for row in matching_customers]
	if len(candidates) > 1 and address:
		address_matches = [customer for customer in candidates if _customer_has_address(customer, address)]
		if len(address_matches) == 1:
			candidates = address_matches
	if len(candidates) > 1:
		frappe.throw(_("More than one Organization Customer matches this name. Staff review is required."))
	if candidates:
		customer = frappe.get_doc("Customer", candidates[0], for_update=True)
		customer.check_permission("read")
		customer.check_permission("write")
		if (
			address
			and _customer_address_names(customer.name)
			and not _customer_has_address(customer.name, address)
		):
			frappe.throw(_("The Organization Customer has a different address. Staff review is required."))
		return customer.name
	return _new_customer(organization_name, "Company").name


def _member_for_organization(customer: str, organization_name: str):
	member_doctype = frappe.qb.DocType("Member")
	members = (
		frappe.qb.from_(member_doctype)
		.select(member_doctype.name)
		.where(member_doctype.customer == customer)
		.orderby(member_doctype.name)
		.for_update()
	).run(pluck=True)
	if len(members) > 1:
		frappe.throw(
			_("This Organization Customer is linked to more than one Member. Staff review is required.")
		)
	if members:
		member = frappe.get_doc("Member", members[0], for_update=True)
		member.check_permission("read")
		member.check_permission("write")
		if member.contact or member.subject_type == "Individual":
			frappe.throw(
				_("The Organization Customer is linked to an individual Member. Staff review is required.")
			)
		if member.subject_type != "Organization":
			member.subject_type = "Organization"
			member.save()
		return member
	return frappe.get_doc(
		{
			"doctype": "Member",
			"member_name": organization_name,
			"subject_type": "Organization",
			"customer": customer,
		}
	).insert()


def _new_customer(customer_name: str, customer_type: str):
	from non_profit.non_profit.doctype.donor.donor import _default_customer_group, _default_territory

	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_type": customer_type,
			"customer_group": _default_customer_group(),
			"territory": _default_territory(),
		}
	).insert()


def _link_contact_to_customer(contact: str, customer, *, email: str | None, set_primary: bool) -> None:
	contact_doc = frappe.get_doc("Contact", contact, for_update=True)
	contact_doc.check_permission("read")
	contact_doc.check_permission("write")
	if not any(
		row.link_doctype == "Customer" and row.link_name == customer.name for row in contact_doc.links
	):
		contact_doc.append("links", {"link_doctype": "Customer", "link_name": customer.name})
		contact_doc.save()

	changed = False
	if set_primary and customer.meta.has_field("customer_primary_contact"):
		primary_contact = cstr(customer.customer_primary_contact).strip()
		if primary_contact and primary_contact != contact:
			frappe.throw(_("The Customer has a different primary Contact. Staff review is required."))
		if primary_contact != contact:
			customer.customer_primary_contact = contact
			changed = True
	if email and customer.meta.has_field("email_id"):
		customer_email = cstr(customer.email_id).strip().lower()
		if customer_email and customer_email != email:
			frappe.throw(_("The Customer has a different email. Staff review is required."))
		if customer_email != email:
			customer.email_id = email
			changed = True
	if changed:
		customer.save()


def _link_organization_contact(contact, customer: str, member: str) -> None:
	contact.check_permission("read")
	contact.check_permission("write")
	changed = False
	for link_doctype, link_name in (("Customer", customer), ("Member", member)):
		if not any(row.link_doctype == link_doctype and row.link_name == link_name for row in contact.links):
			contact.append("links", {"link_doctype": link_doctype, "link_name": link_name})
			changed = True
	if changed:
		contact.save()

	customer_doc = frappe.get_doc("Customer", customer, for_update=True)
	customer_doc.check_permission("read")
	customer_doc.check_permission("write")
	if customer_doc.meta.has_field("customer_primary_contact") and not customer_doc.customer_primary_contact:
		customer_doc.customer_primary_contact = contact.name
		customer_doc.save()


def _resolve_address(
	address: dict[str, str] | None,
	*,
	existing_address=None,
	links: list[tuple[str, str]],
	address_title: str,
	email: str | None,
	phone: str | None,
):
	if not address:
		return None
	if existing_address:
		changed = False
		for link_doctype, link_name in links:
			if not any(
				row.link_doctype == link_doctype and row.link_name == link_name
				for row in existing_address.links
			):
				existing_address.append("links", {"link_doctype": link_doctype, "link_name": link_name})
				changed = True
		if changed:
			existing_address.save()
		return existing_address
	try:
		from good_connector.identity_matching import resolve_or_create_address_from_external_signup
	except ImportError:
		frappe.throw(_("Good Connector identity matching is required for guided Member creation."))

	linked_address_names = _linked_address_names(links)
	for address_name in linked_address_names:
		address_doc = frappe.get_doc("Address", address_name, for_update=True)
		address_doc.check_permission("read")
		address_doc.check_permission("write")
	exact_addresses = [
		address_name for address_name in linked_address_names if _address_matches(address_name, address)
	]
	if len(exact_addresses) > 1:
		frappe.throw(_("More than one exact Address matches this identity. Staff review is required."))
	existing_address = (
		frappe.get_doc("Address", exact_addresses[0], for_update=True) if exact_addresses else None
	)
	if existing_address:
		changed = False
		for link_doctype, link_name in links:
			if not any(
				row.link_doctype == link_doctype and row.link_name == link_name
				for row in existing_address.links
			):
				existing_address.append("links", {"link_doctype": link_doctype, "link_name": link_name})
				changed = True
		if changed:
			existing_address.save()
		return existing_address

	return resolve_or_create_address_from_external_signup(
		address=address,
		links=links,
		address_title=address_title,
		email=email,
		phone=cstr(phone).strip() or None,
		source_doctype="Member",
		source_name=links[-1][1],
	)


def _address_payload(
	*,
	address_line1: str | None,
	postal_code: str | None,
	city: str | None,
	country: str | None,
	required: bool,
) -> dict[str, str] | None:
	line = cstr(address_line1).strip()
	postal_code = cstr(postal_code).strip()
	city = cstr(city).strip()
	if not required and not any((line, postal_code, city)):
		return None
	if not all((line, postal_code, city)):
		frappe.throw(_("Street and house number, postal code, and city must be provided together."))
	country = cstr(country).strip() or cstr(frappe.db.get_default("country")).strip()
	if not country:
		frappe.throw(_("Country is required."))
	country_doc = frappe.get_doc("Country", country, for_update=True)
	country_doc.check_permission("read")
	return {
		"address_line1": line,
		"pincode": postal_code,
		"city": city,
		"country": country,
	}


def _contacts_for_email(email: str) -> list[str]:
	contact_email = frappe.qb.DocType("Contact Email")
	names = set(
		(
			frappe.qb.from_(contact_email)
			.select(contact_email.parent)
			.where(contact_email.email_id == email)
			.where(contact_email.parenttype == "Contact")
		).run(pluck=True)
	)
	contact = frappe.qb.DocType("Contact")
	names.update(
		(frappe.qb.from_(contact).select(contact.name).where(contact.email_id == email).for_update()).run(
			pluck=True
		)
	)
	_lock_names("Contact", names)
	return sorted(names)


def _canonical_members_for_contact(contact: str) -> list[str]:
	member_doctype = frappe.qb.DocType("Member")
	members = set(
		(
			frappe.qb.from_(member_doctype)
			.select(member_doctype.name)
			.where(member_doctype.contact == contact)
			.for_update()
		).run(pluck=True)
	)
	dynamic_link = frappe.qb.DocType("Dynamic Link")
	linked_members = (
		frappe.qb.from_(dynamic_link)
		.select(dynamic_link.link_name)
		.where(dynamic_link.parenttype == "Contact")
		.where(dynamic_link.parent == contact)
		.where(dynamic_link.link_doctype == "Member")
	).run(pluck=True)
	_lock_names("Member", linked_members)
	for member in linked_members:
		if frappe.db.exists("Member", member) and role_uses_canonical_person("Member", member):
			members.add(member)
	return sorted(members)


def _linked_address_names(links: list[tuple[str, str]]) -> list[str]:
	names = set()
	dynamic_link = frappe.qb.DocType("Dynamic Link")
	for link_doctype, link_name in links:
		names.update(
			(
				frappe.qb.from_(dynamic_link)
				.select(dynamic_link.parent)
				.where(dynamic_link.parenttype == "Address")
				.where(dynamic_link.link_doctype == link_doctype)
				.where(dynamic_link.link_name == link_name)
			).run(pluck=True)
		)
	_lock_names("Address", names)
	return sorted(names)


def _customer_address_names(customer: str) -> list[str]:
	return _linked_address_names([("Customer", customer)])


def _customer_has_address(customer: str, address: dict[str, str]) -> bool:
	for address_name in _customer_address_names(customer):
		if _address_matches(address_name, address):
			return True
	return False


def _address_matches(address_name: str, address: dict[str, str]) -> bool:
	address_doctype = frappe.qb.DocType("Address")
	values = (
		frappe.qb.from_(address_doctype)
		.select(
			address_doctype.address_line1,
			address_doctype.pincode,
			address_doctype.city,
			address_doctype.country,
		)
		.where(address_doctype.name == address_name)
		.for_update()
	).run(as_dict=True)
	values = values[0] if values else None
	return bool(values and all(_same_text(values.get(key), address.get(key)) for key in address))


def _lock_names(doctype: str, names) -> None:
	names = sorted(set(names))
	if not names:
		return
	document = frappe.qb.DocType(doctype)
	(
		frappe.qb.from_(document)
		.select(document.name)
		.where(document.name.isin(names))
		.orderby(document.name)
		.for_update()
	).run()


def _acquire_identity_locks(identities: list[tuple[str, str]]) -> None:
	for identity_type, identity_value in sorted(
		set(identities), key=lambda item: (item[0], _normalized_text(item[1]))
	):
		_acquire_identity_lock(identity_type, identity_value)


def _acquire_identity_lock(identity_type: str, identity_value: str) -> None:
	acquire_identity_lock(
		identity_type,
		identity_value,
		busy_message=_("Another Member creation for this identity is still being processed."),
	)


def _required(value: Any, label: str) -> str:
	value = cstr(value).strip()
	if not value:
		frappe.throw(_("{0} is required.").format(label))
	return value


def _email(value: str | None, *, required: bool) -> str:
	value = cstr(value).strip().lower()
	if required and not value:
		frappe.throw(_("Email is required."))
	if value:
		validate_email_address(value, True)
	return value


def _same_text(left: Any, right: Any) -> bool:
	return _normalized_text(left) == _normalized_text(right)


def _normalized_text(value: Any) -> str:
	return " ".join(cstr(value).split()).casefold()


def _phone_key(value: Any) -> str:
	return "".join(character for character in cstr(value) if character.isdigit())
