import frappe
from frappe import _
from frappe.utils import cstr, flt

# Guest-facing donation bounds, shared by every PUBLIC intake path (the
# donate web form here and private checkout flows that import them).
# Desk-entered donations are deliberately unbounded — a staff-recorded
# major gift may exceed the public ceiling.
MIN_PUBLIC_DONATION_AMOUNT = 5
MAX_PUBLIC_DONATION_AMOUNT = 100_000


def validate_public_donation_amount(amount) -> float:
	"""Validate a guest-submitted donation amount against the shared bounds."""
	from math import isfinite

	value = flt(amount)
	if not isfinite(value) or value <= 0:
		frappe.throw(_("Enter a valid donation amount."))
	if value < MIN_PUBLIC_DONATION_AMOUNT:
		frappe.throw(_("The minimum donation amount is CHF {0}.").format(MIN_PUBLIC_DONATION_AMOUNT))
	if value > MAX_PUBLIC_DONATION_AMOUNT:
		frappe.throw(_("Please contact us for donations above CHF {0}.").format(MAX_PUBLIC_DONATION_AMOUNT))
	return value


from non_profit.setup import setup_non_profit


def split_person_name(fullname: str | None) -> tuple[str, str]:
	parts = cstr(fullname).strip().split()
	if not parts:
		return "", ""
	if len(parts) == 1:
		return parts[0], ""
	return parts[0], " ".join(parts[1:])


def ensure_person_contact(contact: str) -> None:
	contact = cstr(contact).strip()
	if not contact or not frappe.db.exists("Contact", contact):
		frappe.throw(_("Contact {0} does not exist").format(frappe.bold(contact)))
	if not frappe.db.has_column("Contact", "npo_identity_kind"):
		return

	identity_kind = frappe.db.get_value("Contact", contact, "npo_identity_kind")
	if identity_kind and identity_kind != "Person":
		frappe.throw(_("Contact {0} is not classified as a person.").format(frappe.bold(contact)))
	if not identity_kind:
		frappe.db.set_value("Contact", contact, "npo_identity_kind", "Person", update_modified=False)


def ensure_canonical_contact_available(role_doctype: str, role_name: str, contact: str) -> None:
	contact_doctype = frappe.qb.DocType("Contact")
	frappe.qb.from_(contact_doctype).select(contact_doctype.name).where(
		contact_doctype.name == contact
	).for_update().run()
	if frappe.db.exists("DocType", "Household Person"):
		household_person = frappe.qb.DocType("Household Person")
		households = (
			frappe.qb.from_(household_person)
			.select(household_person.parent)
			.where(household_person.parenttype == "Household")
			.where(household_person.contact == contact)
			.where(household_person.to_date.isnull() | (household_person.to_date == ""))
		).run(pluck=True)
		if households:
			household = frappe.qb.DocType("Household")
			(
				frappe.qb.from_(household)
				.select(household.name)
				.where(household.name.isin(households))
				.orderby(household.name)
				.for_update()
			).run()
	role = frappe.qb.DocType(role_doctype)
	frappe.qb.from_(role).select(role.name).where(role.name == role_name).for_update().run()

	existing_contact = frappe.db.get_value(role_doctype, role_name, "contact")
	if existing_contact and existing_contact != contact:
		frappe.throw(
			_("{0} {1} is already linked to Contact {2}.").format(
				role_doctype,
				frappe.bold(role_name),
				frappe.bold(existing_contact),
			)
		)
	existing_role = frappe.db.get_value(role_doctype, {"contact": contact}, "name")
	if existing_role and existing_role != role_name:
		frappe.throw(
			_("Contact {0} is already the canonical Contact for {1} {2}.").format(
				frappe.bold(contact),
				role_doctype,
				frappe.bold(existing_role),
			)
		)
	linked_roles = frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": "Contact",
			"parent": contact,
			"link_doctype": role_doctype,
		},
		pluck="link_name",
		order_by="link_name asc",
	)
	conflicting_role = next(
		(
			name
			for name in linked_roles
			if name != role_name
			and frappe.db.exists(role_doctype, name)
			and role_uses_canonical_person(role_doctype, name)
		),
		None,
	)
	if conflicting_role:
		frappe.throw(
			_("Contact {0} is already linked to {1} {2}.").format(
				frappe.bold(contact),
				role_doctype,
				frappe.bold(conflicting_role),
			)
		)

	linked_contacts = frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": "Contact",
			"link_doctype": role_doctype,
			"link_name": role_name,
		},
		pluck="parent",
		order_by="parent asc",
	)
	conflicting_contact = next((name for name in linked_contacts if name != contact), None)
	if conflicting_contact:
		frappe.throw(
			_("{0} {1} is already linked to Contact {2}.").format(
				role_doctype,
				frappe.bold(role_name),
				frappe.bold(conflicting_contact),
			)
		)


def role_uses_canonical_person(role_doctype: str, role_name: str) -> bool:
	if role_doctype not in {"Member", "Donor"}:
		return True
	subject_type = frappe.db.get_value(role_doctype, role_name, "subject_type")
	if subject_type:
		return subject_type == "Individual"
	if role_doctype == "Donor":
		customer = frappe.db.get_value("Donor", role_name, "customer")
		if customer and frappe.db.get_value("Customer", customer, "customer_type") == "Company":
			return False
	return True


def validate_person_role_contact_change(doc) -> None:
	contact = cstr(doc.get("contact")).strip()
	previous = doc.get_doc_before_save()
	previous_contact = cstr(previous.get("contact")).strip() if previous else ""
	if previous and previous_contact != contact:
		frappe.throw(_("Canonical Contact cannot be changed directly. Use the identity linking service."))
	if not contact or previous_contact == contact:
		return
	if not doc.flags.ignore_permissions:
		frappe.get_doc("Contact", contact).check_permission("write")
	ensure_canonical_contact_available(doc.doctype, doc.name, contact)


def validate_contact_identity_kind(contact, method: str | None = None) -> None:
	if contact.get("npo_identity_kind") != "Generic Endpoint":
		return

	for doctype in ("Member", "Donor", "Volunteer"):
		if (
			frappe.db.exists("DocType", doctype)
			and frappe.db.has_column(doctype, "contact")
			and frappe.db.exists(doctype, {"contact": contact.name})
		):
			frappe.throw(_("A Contact used as a person role cannot be classified as a Generic Endpoint."))
		linked_roles = frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Contact",
				"parent": contact.name,
				"link_doctype": doctype,
			},
			pluck="link_name",
		)
		if any(
			frappe.db.exists(doctype, role_name) and role_uses_canonical_person(doctype, role_name)
			for role_name in linked_roles
		):
			frappe.throw(_("A Contact used as a person role cannot be classified as a Generic Endpoint."))
	if (
		frappe.db.exists("DocType", "Household Person")
		and frappe.db.has_column("Household Person", "contact")
		and frappe.db.exists("Household Person", {"contact": contact.name})
	):
		frappe.throw(_("A Contact used in a Household cannot be classified as a Generic Endpoint."))


def get_company():
	company = frappe.defaults.get_defaults().company
	if company:
		return company
	else:
		company = frappe.get_list("Company", limit=1)
		if company:
			return company[0].name
	return None


def before_tests():
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	from non_profit.non_profit.fundraising_setup import ensure_fundraising_fixtures

	use_short_test_host_name()

	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "USD",
				"full_name": "Test User",
				"company_name": "Frappe Care LLC",
				"timezone": "America/New_York",
				"company_abbr": "WP",
				"industry": "Healthcare",
				"country": "United States",
				"fy_start_date": "2021-01-01",
				"fy_end_date": "2021-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
				"domains": ["Non Profit"],
			}
		)
		setup_non_profit()

	ensure_fundraising_fixtures()


def use_short_test_host_name():
	"""Avoid oversized generated OAuth callback URLs during local full test runs."""

	if not frappe.flags.in_test:
		return
	frappe.local.conf.host_name = "http://development16.localhost"
