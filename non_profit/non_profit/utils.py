from typing import Any

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
	skip_hrms_test_record_bootstrap()
	reserve_erpnext_standard_price_lists()

	if not frappe.get_list("Company"):
		# "WP" is ERPNext's own Company test record (Wind Power LLC, in
		# erpnext/setup/doctype/company/test_records.json). This hook runs
		# before those records load, so claiming WP here made every later
		# make_test_records call that reaches Company die on "Abbreviation
		# already used for another company" -- fifteen setUpClass errors, none
		# of which named this function. Keep our test company on an
		# abbreviation ERPNext does not reserve.
		setup_complete(
			{
				"currency": "USD",
				"full_name": "Test User",
				"company_name": "Frappe Care LLC",
				"timezone": "America/New_York",
				"company_abbr": "FCL",
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
		scope_wizard_fiscal_year_to_company("Frappe Care LLC", "2021")

	ensure_test_selling_defaults()
	ensure_fundraising_fixtures()


def scope_wizard_fiscal_year_to_company(company: str, fiscal_year: str):
	"""Stop our Fiscal Year from blocking ERPNext's test fiscal years.

	``erpnext.tests.utils`` seeds ``_Test Fiscal Year <year>`` for every year
	from 2012 to twenty-five years out, and Frappe loads the Fiscal Year test
	records on the way to any doctype that links to one. ``validate_overlap``
	rejects an overlapping year only when *both* rows are global::

	    if not self.get("companies") and not company_for_existing:
	        overlap = True

	The wizard above creates its Fiscal Year global, so ERPNext's
	``_Test Fiscal Year 2021`` cannot be inserted and every test class that
	reaches a Fiscal Year link dies in ``setUpClass``. Naming the company on
	our row is the escape hatch ERPNext's own error message points at, and it
	leaves the year current for this company rather than for the whole site.

	This only ever runs on the branch that just created the company, so it
	never touches a Fiscal Year the site already had. Test-only.
	"""
	if not frappe.db.exists("Fiscal Year", fiscal_year) or not frappe.db.exists("Company", company):
		return

	doc = frappe.get_doc("Fiscal Year", fiscal_year)
	if any(row.company == company for row in doc.get("companies", [])):
		return

	doc.append("companies", {"company": company})
	doc.save(ignore_permissions=True)


def ensure_test_selling_defaults() -> None:
	"""Fill only missing ERPNext party defaults on an isolated test site."""
	if not frappe.flags.in_test:
		return
	for doctype, fieldname in (("Customer Group", "customer_group"), ("Territory", "territory")):
		if frappe.db.get_single_value("Selling Settings", fieldname):
			continue
		leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name", order_by="lft asc")
		if leaf:
			frappe.db.set_single_value("Selling Settings", fieldname, leaf)


def reserve_erpnext_standard_price_lists():
	"""Create ERPNext's Standard price lists before the setup wizard does.

	``erpnext.tests.utils`` runs ``BootStrapTestData()`` at import time, and
	Frappe imports it as soon as a test class walks a link to Company. Its
	``make_records`` de-duplicates on a filter that includes ``currency``, and
	its Standard Buying / Standard Selling records are INR::

	    filters = {"price_list_name": ..., "enabled": ..., "selling": ..., "buying": ..., "currency": "INR"}
	    if not frappe.db.exists(doctype, filters):
	        frappe.get_doc(x).insert()

	The setup wizard below creates both names in the *site* currency. On any
	non-INR site that filter therefore matches nothing, ERPNext inserts, and
	Price List autonames from ``price_list_name`` -- so the insert dies on a
	primary-key duplicate and takes every test class that reaches Company with
	it. That is an upstream ERPNext bug; ``erpnext`` is not ours to patch.

	Seeding the records here, in the exact shape ERPNext looks for, fixes it
	from our side without touching either app. ERPNext then finds them and
	skips, and the wizard's own ``make_records`` passes
	``ignore_if_duplicate=True``, so it skips them too.

	Test-only: this runs from the ``before_tests`` hook and never on a real
	site.
	"""
	if "erpnext" not in frappe.get_installed_apps():
		return

	for price_list_name, buying, selling in (
		("Standard Buying", 1, 0),
		("Standard Selling", 0, 1),
	):
		if frappe.db.exists("Price List", price_list_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": price_list_name,
				"enabled": 1,
				"buying": buying,
				"selling": selling,
				"currency": "INR",
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)


def skip_hrms_test_record_bootstrap():
	"""Keep Frappe's test-record dependency walk out of hrms's test modules.

	Every doctype-folder test class makes Frappe walk its link graph and import
	each dependency's ``test_*`` module. Our doctypes reach hrms ones through
	links such as ``Department.leave_block_list`` and ``Employee``, and every hrms
	test module imports ``hrms.tests.utils``, which runs ``BootStrapTestData()``
	at import time. That bootstrap needs an ``Email Account`` named "Jobs" which
	neither ERPNext nor HRMS creates any more, so it always raises — and on the
	way it would also set ``System Settings`` country to India and commit.

	``get_missing_records_doctypes`` returns before importing anything for a
	doctype it has already visited, and it seeds ``visited`` from
	``frappe.local.test_objects``. Registering hrms's doctypes here therefore
	prunes that whole branch. No non_profit test uses hrms records.
	"""
	if "hrms" not in frappe.get_installed_apps():
		return

	modules = frappe.db.get_values("Module Def", {"app_name": "hrms"}, "name", pluck=True)
	if not modules:
		return

	for doctype in frappe.db.get_values("DocType", {"module": ("in", modules)}, "name", pluck=True):
		frappe.local.test_objects.setdefault(doctype, [])


def use_short_test_host_name():
	"""Avoid oversized generated OAuth callback URLs during local full test runs."""

	if not frappe.flags.in_test:
		return
	frappe.local.conf.host_name = "http://development16.localhost"


def email_template_body(template) -> str:
	"""Canonical Email Template body selection: ``response_html`` when
	``use_html`` is set, else ``response``. Public twin of
	``good_connector.email_utils.email_template_body`` (pinned by the
	connector's parity suite); an HTML-stored template must never render
	empty and a stale plain-text body must never win over the HTML body.
	"""
	from frappe.utils import cint

	if cint(template.get("use_html")):
		return template.get("response_html") or ""
	return template.get("response") or ""


def preferred_contact_email(direct_email, email_rows) -> str | None:
	"""Canonical Contact-email tie-break: ``email_id`` wins, else child rows
	by primary flag, then NEWEST (`creation`), then name.

	Public twin of ``good_connector.recipient.preferred_contact_email``
	(pinned by the connector's correspondence parity suite): one Contact must
	resolve to the same address in every app that mails it.
	"""
	from frappe.utils import cint, cstr

	if email := cstr(direct_email).strip():
		return email
	candidates = [row for row in email_rows if cstr(row.get("email_id")).strip()]
	candidates.sort(
		key=lambda row: (
			cint(row.get("is_primary")),
			cstr(row.get("creation")),
			cstr(row.get("name")),
		),
		reverse=True,
	)
	return cstr(candidates[0].get("email_id")).strip() if candidates else None


def customer_display_name(customer_name: Any, name_additional: Any = None, fallback: Any = None) -> str:
	"""Return the canonical customer name plus optional additional name."""
	parts = [cstr(customer_name).strip(), cstr(name_additional).strip()]
	display_name = " - ".join(part for part in parts if part)
	return display_name or cstr(fallback).strip()


def contact_display_name(contact_row: Any, fallback: Any = None) -> str:
	"""Return full name, first/last name, then an explicit or row fallback."""
	full_name = cstr(contact_row.get("full_name")).strip()
	if full_name:
		return full_name
	name_parts = [contact_row.get("first_name"), contact_row.get("last_name")]
	joined = " ".join(part for part in (cstr(p).strip() for p in name_parts) if part)
	return joined or cstr(fallback if fallback is not None else contact_row.get("name")).strip()
