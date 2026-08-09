from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr

SUPPORTED_SOURCE_DOCTYPES = ("Contact", "Member", "Donor", "Household", "Customer")
MAX_SOURCE_REFERENCES = 500
MAX_RELATED_ROWS = 5000

CANONICAL_SUBJECT_DOCTYPES = {
	"Contact": "Contact",
	"Person": "Contact",
	"Customer": "Customer",
	"Organization": "Customer",
	"Household": "Household",
}
RELATED_SOURCE_FIELDS = (
	("contacts", "Contact"),
	("members", "Member"),
	("donors", "Donor"),
	("customers", "Customer"),
)

MISSING_CANONICAL_SUBJECT = "MISSING_CANONICAL_SUBJECT"
MISSING_PERSON_CONTACT = "MISSING_PERSON_CONTACT"
AMBIGUOUS_PERSON_CONTACT = "AMBIGUOUS_PERSON_CONTACT"
MISSING_ORGANIZATION = "MISSING_ORGANIZATION"
MISSING_HOUSEHOLD = "MISSING_HOUSEHOLD"
AMBIGUOUS_HOUSEHOLD = "AMBIGUOUS_HOUSEHOLD"
MISSING_HOUSEHOLD_PEOPLE = "MISSING_HOUSEHOLD_PEOPLE"
UNSUPPORTED_SUBJECT_TYPE = "UNSUPPORTED_SUBJECT_TYPE"
MISSING_ADDRESSEE = "MISSING_ADDRESSEE"
MISSING_LANGUAGE = "MISSING_LANGUAGE"
MISSING_ADDRESS = "MISSING_ADDRESS"
AMBIGUOUS_ADDRESS = "AMBIGUOUS_ADDRESS"

CORRESPONDENCE_ISSUE_CODES = (
	MISSING_CANONICAL_SUBJECT,
	MISSING_PERSON_CONTACT,
	AMBIGUOUS_PERSON_CONTACT,
	MISSING_ORGANIZATION,
	MISSING_HOUSEHOLD,
	AMBIGUOUS_HOUSEHOLD,
	MISSING_HOUSEHOLD_PEOPLE,
	UNSUPPORTED_SUBJECT_TYPE,
	MISSING_ADDRESSEE,
	MISSING_LANGUAGE,
	MISSING_ADDRESS,
	AMBIGUOUS_ADDRESS,
)

SOURCE_FIELDS = {
	"Contact": (
		"name",
		"first_name",
		"middle_name",
		"last_name",
		"full_name",
		"salutation",
		"title",
		"preferred_language",
		"npo_identity_kind",
		"address",
	),
	"Member": ("name", "member_name", "subject_type", "contact", "customer", "household"),
	"Donor": (
		"name",
		"donor_name",
		"subject_type",
		"contact",
		"customer",
		"subject_household",
		"household",
		"preferred_language",
	),
	"Household": ("name", "household_name", "preferred_language"),
	"Customer": (
		"name",
		"customer_name",
		"customer_type",
		"language",
		"disabled",
		"npo_subject_type",
		"npo_contact",
		"npo_household",
		"household",
		"customer_primary_contact",
		"customer_primary_address",
	),
}

CONTACT_FIELDS = SOURCE_FIELDS["Contact"]
CUSTOMER_FIELDS = SOURCE_FIELDS["Customer"]
HOUSEHOLD_FIELDS = SOURCE_FIELDS["Household"]
ADDRESS_FIELDS = (
	"name",
	"address_type",
	"address_line1",
	"address_line2",
	"pincode",
	"city",
	"county",
	"state",
	"country",
	"is_primary_address",
	"is_shipping_address",
	"disabled",
)


@dataclass(frozen=True)
class _CorrespondenceReference:
	source: tuple[str, str]
	canonical_subject: tuple[str, str] | None = None
	related_sources: tuple[tuple[str, str], ...] = ()


def get_correspondence_profile(
	source_doctype: str | None = None,
	source_name: str | None = None,
	*,
	canonical_subject_type: str | None = None,
	canonical_subject: str | None = None,
	contacts: Sequence[str] | None = None,
	members: Sequence[str] | None = None,
	donors: Sequence[str] | None = None,
	customers: Sequence[str] | None = None,
	as_of: Any | None = None,
	respect_permissions: bool = False,
) -> dict[str, Any]:
	"""Resolve one source or one already-consolidated canonical subject.

	The keyword form is the narrow adapter used by postal campaign consumers
	after they have already deduplicated source roles and applied any as-of audience
	filter. Household people themselves always follow non_profit's current-row
	definition (no ``to_date``).
	"""
	del as_of
	canonical_subject_type = cstr(canonical_subject_type).strip()
	canonical_subject = cstr(canonical_subject).strip()
	if canonical_subject_type or canonical_subject:
		if source_doctype or source_name:
			frappe.throw(_("Use either a source reference or a canonical correspondence subject, not both."))
		if canonical_subject_type not in CANONICAL_SUBJECT_DOCTYPES or not canonical_subject:
			frappe.throw(_("A supported canonical correspondence subject and name are required."))
		return get_correspondence_profiles(
			[
				{
					"canonical_subject_type": canonical_subject_type,
					"canonical_subject": canonical_subject,
					"contacts": contacts,
					"members": members,
					"donors": donors,
					"customers": customers,
				}
			],
			respect_permissions=respect_permissions,
		)[0]
	elif contacts or members or donors or customers:
		frappe.throw(_("Related correspondence sources require a canonical subject."))

	return get_correspondence_profiles(
		[(cstr(source_doctype), cstr(source_name))],
		respect_permissions=respect_permissions,
	)[0]


def get_correspondence_profiles(
	source_references: Iterable[Mapping[str, Any] | tuple[str, str]],
	*,
	respect_permissions: bool = False,
) -> list[dict[str, Any]]:
	"""Resolve a bounded list of Direct Mail source references in input order.

	The service is intentionally not whitelisted. A consuming app owns audience
	permissions and policy; this function only resolves canonical NPO identity and
	current correspondence candidates without writing to master data. Consumers
	that expose results to the current user pass ``respect_permissions=True`` so
	permission-invisible related masters cannot influence the profile.
	"""
	references = _normalize_source_references(source_references)
	if not references:
		return []
	return _CorrespondenceProfileResolver(
		references,
		respect_permissions=respect_permissions,
	).resolve()


class _CorrespondenceProfileResolver:
	def __init__(
		self,
		references: list[_CorrespondenceReference],
		*,
		respect_permissions: bool = False,
	):
		self.references = references
		self.respect_permissions = respect_permissions
		self.source_rows: dict[tuple[str, str], Mapping[str, Any]] = {}
		self.contacts: dict[str, Mapping[str, Any]] = {}
		self.customers: dict[str, Mapping[str, Any]] = {}
		self.households: dict[str, Mapping[str, Any]] = {}
		self.customer_contacts: dict[str, list[str]] = defaultdict(list)
		self.household_people: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
		self.contact_households: dict[str, list[str]] = defaultdict(list)

	def resolve(self) -> list[dict[str, Any]]:
		self._load_sources()
		self._load_identity_dependencies()
		resolutions = [self._resolve_reference(reference) for reference in self.references]
		self._load_current_households(resolutions)
		profiles = [self._build_profile(resolution) for resolution in resolutions]
		self._attach_address_candidates(profiles)
		for profile in profiles:
			profile["issue_codes"] = [issue["code"] for issue in profile["issues"]]
			profile["address_name"] = profile["address"]["name"] if profile.get("address") else None
		return profiles

	def _load_sources(self) -> None:
		names_by_doctype: dict[str, set[str]] = defaultdict(set)
		for reference in self.references:
			for doctype, name in (reference.source, *reference.related_sources):
				names_by_doctype[doctype].add(name)

		for doctype, names in names_by_doctype.items():
			rows = _fetch_rows(
				doctype,
				names,
				SOURCE_FIELDS[doctype],
				respect_permissions=self.respect_permissions,
			)
			for name, row in rows.items():
				self.source_rows[(doctype, name)] = row
			missing = sorted(names - set(rows))
			if missing:
				frappe.throw(
					_("{0} {1} does not exist.").format(doctype, frappe.bold(missing[0])),
					frappe.DoesNotExistError,
				)

		self.contacts.update(
			{name: row for (doctype, name), row in self.source_rows.items() if doctype == "Contact"}
		)
		self.customers.update(
			{name: row for (doctype, name), row in self.source_rows.items() if doctype == "Customer"}
		)
		self.households.update(
			{name: row for (doctype, name), row in self.source_rows.items() if doctype == "Household"}
		)

	def _load_identity_dependencies(self) -> None:
		customer_names = set(self.customers)
		contact_names = set(self.contacts)
		household_names = set(self.households)
		for (doctype, _name), row in self.source_rows.items():
			if doctype in {"Member", "Donor"}:
				if row.get("customer"):
					customer_names.add(row["customer"])
				if row.get("contact"):
					contact_names.add(row["contact"])
			if doctype == "Donor" and row.get("subject_household"):
				household_names.add(row["subject_household"])

		self.customers.update(
			_fetch_rows(
				"Customer",
				customer_names,
				CUSTOMER_FIELDS,
				respect_permissions=self.respect_permissions,
			)
		)
		for customer in self.customers.values():
			for fieldname in ("npo_contact", "customer_primary_contact"):
				if contact := customer.get(fieldname):
					contact_names.add(contact)
					if contact not in self.customer_contacts[customer.name]:
						self.customer_contacts[customer.name].append(contact)
			if customer.get("npo_subject_type") == "Household":
				if household := customer.get("npo_household") or customer.get("household"):
					household_names.add(household)
		self.households.update(
			_fetch_rows(
				"Household",
				household_names,
				HOUSEHOLD_FIELDS,
				respect_permissions=self.respect_permissions,
			)
		)

		if customer_names:
			link_rows = frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Contact",
					"link_doctype": "Customer",
					"link_name": ["in", sorted(customer_names)],
				},
				fields=["parent", "link_name", "idx"],
				order_by="link_name asc, idx asc, parent asc",
				limit=MAX_RELATED_ROWS + 1,
			)
			_assert_related_row_limit(link_rows)
			for row in link_rows:
				if row.parent not in self.customer_contacts[row.link_name]:
					self.customer_contacts[row.link_name].append(row.parent)
				contact_names.add(row.parent)

		self.contacts.update(
			_fetch_rows(
				"Contact",
				contact_names,
				CONTACT_FIELDS,
				respect_permissions=self.respect_permissions,
			)
		)

	def _resolve_reference(self, reference: _CorrespondenceReference) -> dict[str, Any]:
		resolution = self._resolve_source(reference.source)
		if reference.canonical_subject:
			resolution["canonical_doctype"], resolution["canonical_name"] = reference.canonical_subject
			resolution["issues"] = [
				issue for issue in resolution["issues"] if issue["code"] != MISSING_CANONICAL_SUBJECT
			]
		resolution["related_sources"] = reference.related_sources
		return resolution

	def _resolve_source(self, reference: tuple[str, str]) -> dict[str, Any]:
		doctype, name = reference
		row = self.source_rows[reference]
		if doctype == "Contact":
			return self._person_resolution(reference, name)
		if doctype == "Household":
			return self._household_resolution(reference, name)
		if doctype == "Customer":
			return self._customer_resolution(reference, name)
		if doctype == "Member":
			if row.get("contact"):
				return self._person_resolution(reference, row["contact"], customer=row.get("customer"))
			if row.get("subject_type") == "Organization":
				return self._organization_resolution(reference, row.get("customer"))
			if row.get("subject_type") == "Individual":
				return self._missing_resolution(reference, "Person", MISSING_PERSON_CONTACT)
			if row.get("subject_type"):
				return self._missing_resolution(reference, None, UNSUPPORTED_SUBJECT_TYPE)
			if row.get("customer"):
				return self._customer_resolution(reference, row["customer"])
			return self._missing_resolution(reference, None, MISSING_CANONICAL_SUBJECT)

		if row.get("subject_type") == "Household" or (
			not row.get("subject_type") and row.get("subject_household")
		):
			return self._household_resolution(
				reference,
				row.get("subject_household"),
				customer=row.get("customer"),
			)
		if row.get("contact"):
			return self._person_resolution(reference, row["contact"], customer=row.get("customer"))
		if row.get("subject_type") == "Organization":
			return self._organization_resolution(reference, row.get("customer"))
		if row.get("subject_type") == "Individual":
			return self._missing_resolution(reference, "Person", MISSING_PERSON_CONTACT)
		if row.get("subject_type"):
			return self._missing_resolution(
				reference,
				None,
				UNSUPPORTED_SUBJECT_TYPE,
				customer=row.get("customer"),
			)
		if row.get("customer"):
			return self._customer_resolution(reference, row["customer"])
		return self._missing_resolution(reference, None, UNSUPPORTED_SUBJECT_TYPE)

	def _customer_resolution(self, reference: tuple[str, str], customer_name: str | None) -> dict[str, Any]:
		customer = self.customers.get(cstr(customer_name))
		if not customer:
			return self._missing_resolution(reference, None, MISSING_CANONICAL_SUBJECT)
		subject_type = cstr(customer.get("npo_subject_type")).strip()
		if subject_type == "Household":
			return self._household_resolution(
				reference,
				customer.get("npo_household") or customer.get("household"),
				customer=customer.name,
			)
		if subject_type == "Organization":
			return self._organization_resolution(reference, customer.name)
		if subject_type == "Person" or (not subject_type and customer.get("customer_type") == "Individual"):
			contact, issue_code = self._person_contact_for_customer(customer)
			if issue_code:
				return self._missing_resolution(
					reference,
					"Person",
					issue_code,
					customer=customer.name,
				)
			return self._person_resolution(reference, contact, customer=customer.name)
		if not subject_type and customer.get("customer_type") in {"Company", "Partnership"}:
			return self._organization_resolution(reference, customer.name)
		return self._missing_resolution(reference, None, UNSUPPORTED_SUBJECT_TYPE, customer=customer.name)

	def _person_contact_for_customer(self, customer: Mapping[str, Any]) -> tuple[str | None, str | None]:
		for fieldname in ("npo_contact", "customer_primary_contact"):
			if contact := cstr(customer.get(fieldname)).strip():
				self._reject_generic_endpoint(contact)
				return contact, None

		person_contacts = sorted(
			contact
			for contact in self.customer_contacts.get(customer["name"], [])
			if contact in self.contacts
			and self.contacts[contact].get("npo_identity_kind") != "Generic Endpoint"
		)
		if len(person_contacts) == 1:
			return person_contacts[0], None
		if len(person_contacts) > 1:
			return None, AMBIGUOUS_PERSON_CONTACT
		return None, MISSING_PERSON_CONTACT

	def _person_resolution(
		self,
		reference: tuple[str, str],
		contact: str | None,
		*,
		customer: str | None = None,
	) -> dict[str, Any]:
		contact = cstr(contact).strip()
		if not contact or contact not in self.contacts:
			return self._missing_resolution(
				reference,
				"Person",
				MISSING_PERSON_CONTACT,
				customer=customer,
			)
		self._reject_generic_endpoint(contact)
		return self._resolution(
			reference,
			"Person",
			"Contact",
			contact,
			contact=contact,
			customer=customer,
		)

	def _organization_resolution(self, reference: tuple[str, str], customer: str | None) -> dict[str, Any]:
		customer = cstr(customer).strip()
		if not customer or customer not in self.customers:
			return self._missing_resolution(reference, "Organization", MISSING_ORGANIZATION)
		return self._resolution(
			reference,
			"Organization",
			"Customer",
			customer,
			customer=customer,
		)

	def _household_resolution(
		self,
		reference: tuple[str, str],
		household: str | None,
		*,
		customer: str | None = None,
	) -> dict[str, Any]:
		household = cstr(household).strip()
		if not household or household not in self.households:
			return self._missing_resolution(
				reference,
				"Household",
				MISSING_HOUSEHOLD,
				customer=customer,
			)
		return self._resolution(
			reference,
			"Household",
			"Household",
			household,
			customer=customer,
			household=household,
		)

	def _resolution(
		self,
		reference: tuple[str, str],
		subject_type: str | None,
		canonical_doctype: str | None,
		canonical_name: str | None,
		*,
		contact: str | None = None,
		customer: str | None = None,
		household: str | None = None,
		issues: list[dict[str, Any]] | None = None,
	) -> dict[str, Any]:
		return {
			"source": reference,
			"subject_type": subject_type,
			"canonical_doctype": canonical_doctype,
			"canonical_name": canonical_name,
			"contact": contact,
			"customer": customer,
			"household": household,
			"issues": issues or [],
		}

	def _missing_resolution(
		self,
		reference: tuple[str, str],
		subject_type: str | None,
		issue_code: str,
		*,
		customer: str | None = None,
	) -> dict[str, Any]:
		issues: list[dict[str, Any]] = []
		_add_issue(issues, issue_code)
		_add_issue(issues, MISSING_CANONICAL_SUBJECT)
		return self._resolution(reference, subject_type, None, None, customer=customer, issues=issues)

	def _reject_generic_endpoint(self, contact: str) -> None:
		row = self.contacts.get(contact)
		if row and row.get("npo_identity_kind") == "Generic Endpoint":
			frappe.throw(
				_(
					"Contact {0} is a Generic Endpoint and cannot be used as a person correspondence subject."
				).format(frappe.bold(contact))
			)

	def _load_current_households(self, resolutions: list[dict[str, Any]]) -> None:
		contact_names = {row["contact"] for row in resolutions if row.get("contact")}
		household_names = {row["household"] for row in resolutions if row.get("household")}
		if not contact_names and not household_names:
			return

		household_person = frappe.qb.DocType("Household Person")
		scope = None
		if contact_names:
			scope = household_person.contact.isin(sorted(contact_names))
		if household_names:
			household_scope = household_person.parent.isin(sorted(household_names))
			scope = household_scope if scope is None else scope | household_scope
		rows = (
			frappe.qb.from_(household_person)
			.select(
				household_person.name,
				household_person.parent,
				household_person.contact,
				household_person.relationship,
				household_person.from_date,
				household_person.to_date,
				household_person.is_primary,
				household_person.idx,
			)
			.where(household_person.parenttype == "Household")
			.where(household_person.to_date.isnull() | (household_person.to_date == ""))
			.where(scope)
			.limit(MAX_RELATED_ROWS + 1)
		).run(as_dict=True)
		_assert_related_row_limit(rows)
		rows.sort(key=lambda row: (row.parent, -cint(row.is_primary), row.contact, cint(row.idx)))

		household_names.update(row.parent for row in rows)
		self.households.update(
			_fetch_rows(
				"Household",
				household_names,
				HOUSEHOLD_FIELDS,
				respect_permissions=self.respect_permissions,
			)
		)
		self.contacts.update(
			_fetch_rows(
				"Contact",
				{row.contact for row in rows},
				CONTACT_FIELDS,
				respect_permissions=self.respect_permissions,
			)
		)
		for row in rows:
			if row.parent not in self.households:
				continue
			self.household_people[row.parent].append(row)
			if row.contact in self.contacts and row.parent not in self.contact_households[row.contact]:
				self.contact_households[row.contact].append(row.parent)

	def _build_profile(self, resolution: dict[str, Any]) -> dict[str, Any]:
		doctype, name = resolution["source"]
		issues = list(resolution["issues"])
		household = resolution.get("household")
		if resolution.get("subject_type") == "Person" and resolution.get("contact"):
			households = sorted(self.contact_households.get(resolution["contact"], []))
			if len(households) == 1:
				household = households[0]
			elif len(households) > 1:
				_add_issue(issues, AMBIGUOUS_HOUSEHOLD, households=households)

		household_people = self._household_person_components(household)
		if resolution.get("subject_type") == "Household" and not household_people:
			_add_issue(issues, MISSING_HOUSEHOLD_PEOPLE)

		people = self._profile_people(resolution, household_people)
		addressee, name_components = self._addressee(resolution, people)
		if not addressee:
			_add_issue(issues, MISSING_ADDRESSEE)
		language, language_provenance = self._language(resolution, household, people)
		if not language:
			_add_issue(issues, MISSING_LANGUAGE)

		canonical_subject = None
		if resolution.get("canonical_doctype") and resolution.get("canonical_name"):
			canonical_subject = {
				"doctype": resolution["canonical_doctype"],
				"name": resolution["canonical_name"],
			}
		profile = {
			"source": {"doctype": doctype, "name": name},
			"subject_type": resolution.get("subject_type"),
			"canonical_subject": canonical_subject,
			"related_sources": [
				{"doctype": related_doctype, "name": related_name}
				for related_doctype, related_name in resolution.get("related_sources", ())
			],
			"contact": resolution.get("contact"),
			"customer": resolution.get("customer"),
			"household": household,
			"people": people,
			"household_people": household_people,
			"inaccessible_contacts": self._inaccessible_contacts(resolution, household),
			"addressee": addressee,
			"name_components": name_components,
			"language": language,
			"language_provenance": language_provenance,
			"address": None,
			"address_candidates": [],
			"issues": issues,
		}
		profile["_address_targets"] = self._address_targets(profile, resolution)
		return profile

	def _inaccessible_contacts(
		self,
		resolution: Mapping[str, Any],
		household: str | None,
	) -> list[str]:
		contact_names = {row.contact for row in self.household_people.get(cstr(household), []) if row.contact}
		customer_names = {cstr(resolution.get("customer")).strip()} - {""}
		for doctype, name in resolution.get("related_sources", ()):
			if doctype == "Contact":
				contact_names.add(name)
			elif doctype == "Customer":
				customer_names.add(name)
			elif doctype in {"Member", "Donor"}:
				row = self.source_rows[(doctype, name)]
				if contact := cstr(row.get("contact")).strip():
					contact_names.add(contact)
				if customer := cstr(row.get("customer")).strip():
					customer_names.add(customer)
		for customer in customer_names:
			contact_names.update(self.customer_contacts.get(customer, []))
		return sorted(contact_names - set(self.contacts))

	def _profile_people(
		self, resolution: Mapping[str, Any], household_people: list[dict[str, Any]]
	) -> list[dict[str, Any]]:
		if resolution.get("subject_type") == "Household":
			return household_people
		if resolution.get("subject_type") == "Person" and resolution.get("contact") in self.contacts:
			return [self._contact_components(resolution["contact"])]
		if resolution.get("subject_type") != "Organization" or not resolution.get("customer"):
			return []
		customer = self.customers.get(resolution["customer"], {})
		primary_contact = customer.get("customer_primary_contact")
		contacts = [
			contact
			for contact in self.customer_contacts.get(resolution["customer"], [])
			if contact in self.contacts
			and self.contacts[contact].get("npo_identity_kind") != "Generic Endpoint"
		]
		contacts.sort(key=lambda contact: (0 if contact == primary_contact else 1, contact))
		return [self._contact_components(contact) for contact in contacts]

	def _household_person_components(self, household: str | None) -> list[dict[str, Any]]:
		people = []
		for row in self.household_people.get(cstr(household), []):
			if row.contact not in self.contacts:
				continue
			self._reject_generic_endpoint(row.contact)
			person = self._contact_components(row.contact)
			person.update(
				{
					"relationship": row.relationship,
					"from_date": row.from_date,
					"to_date": row.to_date,
					"is_primary": cint(row.is_primary),
				}
			)
			people.append(person)
		return people

	def _contact_components(self, contact: str) -> dict[str, Any]:
		row = self.contacts[contact]
		display_name = cstr(row.get("full_name")).strip() or " ".join(
			part
			for part in (
				cstr(row.get("first_name")).strip(),
				cstr(row.get("middle_name")).strip(),
				cstr(row.get("last_name")).strip(),
			)
			if part
		)
		display_name = display_name or contact
		title = cstr(row.get("title")).strip()
		return {
			"contact": contact,
			"title": title or None,
			"salutation": row.get("salutation"),
			"first_name": cstr(row.get("first_name")).strip() or None,
			"middle_name": cstr(row.get("middle_name")).strip() or None,
			"last_name": cstr(row.get("last_name")).strip() or None,
			"display_name": display_name,
			"addressee": " ".join(part for part in (title, display_name) if part),
		}

	def _addressee(
		self, resolution: Mapping[str, Any], people: list[dict[str, Any]]
	) -> tuple[str | None, dict[str, Any]]:
		subject_type = resolution.get("subject_type")
		if subject_type == "Person" and people:
			return people[0]["addressee"], dict(people[0])
		if subject_type == "Organization" and resolution.get("customer") in self.customers:
			customer = self.customers[resolution["customer"]]
			organization_name = cstr(customer.get("customer_name")).strip() or customer["name"]
			return organization_name, {"organization_name": organization_name, "people": people}
		if subject_type == "Household" and resolution.get("household") in self.households:
			household = self.households[resolution["household"]]
			household_name = cstr(household.get("household_name")).strip() or household["name"]
			return household_name, {"household_name": household_name, "people": people}
		return None, {}

	def _language(
		self,
		resolution: Mapping[str, Any],
		household: str | None,
		people: list[dict[str, Any]],
	) -> tuple[str | None, dict[str, str] | None]:
		candidates: list[tuple[Any, str, str, str]] = []
		if household in self.households:
			candidates.append(
				(
					self.households[household].get("preferred_language"),
					"Household",
					household,
					"preferred_language",
				)
			)
		related_pairs = self._related_identity_pairs(resolution)
		source_doctype, source_name = resolution["source"]
		donor_candidates: list[tuple[Any, str, str, str]] = []
		donor_names = [source_name] if source_doctype == "Donor" else []
		for donor_name in sorted(name for doctype, name in related_pairs if doctype == "Donor"):
			if donor_name not in donor_names:
				donor_names.append(donor_name)
		for donor_name in donor_names:
			donor_candidates.append(
				(
					self.source_rows[("Donor", donor_name)].get("preferred_language"),
					"Donor",
					donor_name,
					"preferred_language",
				)
			)
		customer_candidates: list[tuple[Any, str, str, str]] = []
		customer_names = []
		if resolution.get("customer") in self.customers:
			customer_names.append(resolution["customer"])
		for customer_name in sorted(name for doctype, name in related_pairs if doctype == "Customer"):
			if customer_name not in customer_names:
				customer_names.append(customer_name)
		for customer_name in customer_names:
			customer_candidates.append(
				(
					self.customers[customer_name].get("language"),
					"Customer",
					customer_name,
					"language",
				)
			)
		if resolution.get("subject_type") == "Organization":
			candidates.extend(customer_candidates)
			candidates.extend(donor_candidates)
		else:
			candidates.extend(donor_candidates)
			candidates.extend(customer_candidates)
		contact_names = []
		if resolution.get("contact"):
			contact_names.append(resolution["contact"])
		contact_names.extend(person["contact"] for person in people if person["contact"] not in contact_names)
		for contact_name in sorted(name for doctype, name in related_pairs if doctype == "Contact"):
			if contact_name not in contact_names:
				contact_names.append(contact_name)
		for contact in contact_names:
			if contact in self.contacts:
				candidates.append(
					(
						self.contacts[contact].get("preferred_language"),
						"Contact",
						contact,
						"preferred_language",
					)
				)

		for value, doctype, name, fieldname in candidates:
			if language := cstr(value).strip():
				return language, {"doctype": doctype, "name": name, "fieldname": fieldname}
		return None, None

	def _related_identity_pairs(self, resolution: Mapping[str, Any]) -> set[tuple[str, str]]:
		pairs = set(resolution.get("related_sources", ()))
		for doctype, name in tuple(pairs):
			if doctype not in {"Member", "Donor"}:
				continue
			row = self.source_rows[(doctype, name)]
			if (contact := cstr(row.get("contact")).strip()) and contact in self.contacts:
				pairs.add(("Contact", contact))
			if (customer := cstr(row.get("customer")).strip()) and customer in self.customers:
				pairs.add(("Customer", customer))
		return pairs

	def _address_targets(
		self, profile: Mapping[str, Any], resolution: Mapping[str, Any]
	) -> set[tuple[str, str]]:
		targets = {(profile["source"]["doctype"], profile["source"]["name"])}
		if profile.get("canonical_subject"):
			targets.add((profile["canonical_subject"]["doctype"], profile["canonical_subject"]["name"]))
		for doctype, fieldname in (
			("Contact", "contact"),
			("Customer", "customer"),
			("Household", "household"),
		):
			if profile.get(fieldname):
				targets.add((doctype, profile[fieldname]))
		if profile.get("subject_type") == "Household":
			targets.update(("Contact", person["contact"]) for person in profile["household_people"])
		targets.update(self._related_identity_pairs(resolution))
		return targets

	def _attach_address_candidates(self, profiles: list[dict[str, Any]]) -> None:
		target_pairs = set().union(*(profile["_address_targets"] for profile in profiles))
		if not target_pairs:
			return
		names_by_doctype: dict[str, set[str]] = defaultdict(set)
		for doctype, name in target_pairs:
			names_by_doctype[doctype].add(name)
		link_rows = []
		for doctype, names in sorted(names_by_doctype.items()):
			remaining = MAX_RELATED_ROWS - len(link_rows)
			rows = frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Address",
					"link_doctype": doctype,
					"link_name": ["in", sorted(names)],
				},
				fields=["parent", "link_doctype", "link_name"],
				order_by="parent asc, link_name asc",
				limit=remaining + 1,
			)
			link_rows.extend(rows)
			_assert_related_row_limit(link_rows)

		addresses_by_target: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
		address_names = set()
		for row in link_rows:
			target = (row.link_doctype, row.link_name)
			if target not in target_pairs:
				continue
			addresses_by_target[target].append((row.parent, "Dynamic Link"))
			address_names.add(row.parent)
		for doctype, name in target_pairs:
			address_name = None
			via = None
			if doctype == "Contact" and name in self.contacts:
				address_name = self.contacts[name].get("address")
				via = "Contact.address"
			elif doctype == "Customer" and name in self.customers:
				address_name = self.customers[name].get("customer_primary_address")
				via = "Customer.customer_primary_address"
			if address_name:
				addresses_by_target[(doctype, name)].append((address_name, via))
				address_names.add(address_name)
		_assert_related_row_limit(address_names)

		addresses = _fetch_rows(
			"Address",
			address_names,
			ADDRESS_FIELDS,
			extra_filters={"disabled": 0},
			respect_permissions=self.respect_permissions,
		)
		for profile in profiles:
			provenance_by_address: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
			for target in profile.pop("_address_targets"):
				for address_name, via in addresses_by_target.get(target, []):
					if address_name in addresses:
						provenance_by_address[address_name].add((target[0], target[1], via))
			candidates = [
				_address_candidate(addresses[address_name], provenance)
				for address_name, provenance in provenance_by_address.items()
			]
			candidates.sort(
				key=lambda candidate: (
					-cint(candidate["is_primary_address"]),
					-cint(candidate["is_shipping_address"]),
					candidate["name"],
				)
			)
			profile["address_candidates"] = candidates
			if selected_address := _select_address(candidates):
				profile["address"] = selected_address
			elif not candidates:
				_add_issue(profile["issues"], MISSING_ADDRESS)
			else:
				_add_issue(
					profile["issues"],
					AMBIGUOUS_ADDRESS,
					addresses=[candidate["name"] for candidate in candidates],
				)


def _normalize_source_references(
	source_references: Iterable[Mapping[str, Any] | tuple[str, str]],
) -> list[_CorrespondenceReference]:
	if isinstance(source_references, (str, bytes, Mapping)):
		frappe.throw(_("Correspondence source references must be a list."))
	references = _bounded_sequence(
		source_references,
		MAX_SOURCE_REFERENCES,
		invalid_message=_("Correspondence source references must be a list."),
		limit_message=_("At most {0} correspondence source references can be resolved at once.").format(
			MAX_SOURCE_REFERENCES
		),
	)
	normalized: list[_CorrespondenceReference] = []
	related_count = 0
	for reference in references:
		if isinstance(reference, Mapping):
			if "canonical_subject_type" in reference or "canonical_subject" in reference:
				canonical_subject_type = cstr(reference.get("canonical_subject_type")).strip()
				doctype = CANONICAL_SUBJECT_DOCTYPES.get(canonical_subject_type)
				name = cstr(reference.get("canonical_subject")).strip()
				if not doctype or not name:
					frappe.throw(_("A supported canonical correspondence subject and name are required."))
				related_sources, consumed = _normalize_related_sources(
					reference, MAX_RELATED_ROWS - related_count
				)
				related_count += consumed
				normalized.append(
					_CorrespondenceReference(
						source=(doctype, name),
						canonical_subject=(doctype, name),
						related_sources=related_sources,
					)
				)
				continue
			if any(fieldname in reference for fieldname, _doctype in RELATED_SOURCE_FIELDS):
				frappe.throw(_("Related correspondence sources require a canonical subject."))
			doctype = cstr(reference.get("doctype") or reference.get("reference_doctype")).strip()
			name = cstr(reference.get("name") or reference.get("reference_name")).strip()
		elif isinstance(reference, (tuple, list)) and len(reference) == 2:
			doctype, name = (cstr(value).strip() for value in reference)
		else:
			frappe.throw(_("Each correspondence source must contain a DocType and document name."))
		if doctype not in SUPPORTED_SOURCE_DOCTYPES:
			frappe.throw(
				_("Correspondence source DocType {0} is not supported.").format(frappe.bold(doctype))
			)
		if not name:
			frappe.throw(_("A document name is required for every correspondence source."))
		normalized.append(_CorrespondenceReference(source=(doctype, name)))
	return normalized


def _normalize_related_sources(
	reference: Mapping[str, Any], remaining: int
) -> tuple[tuple[tuple[str, str], ...], int]:
	related_sources = []
	consumed = 0
	for fieldname, doctype in RELATED_SOURCE_FIELDS:
		values = reference.get(fieldname)
		if values is None:
			continue
		items = _bounded_sequence(
			values,
			remaining - consumed,
			invalid_message=_("Related {0} references must be a list.").format(doctype),
			limit_message=_("At most {0} related correspondence sources can be supplied at once.").format(
				MAX_RELATED_ROWS
			),
		)
		consumed += len(items)
		names = sorted({cstr(name).strip() for name in items if cstr(name).strip()})
		related_sources.extend((doctype, name) for name in names)
	return tuple(related_sources), consumed


def _bounded_sequence(
	values: Iterable[Any],
	limit: int,
	*,
	invalid_message: str,
	limit_message: str,
) -> list[Any]:
	if isinstance(values, (str, bytes, Mapping)):
		frappe.throw(invalid_message)
	try:
		iterator = iter(values)
	except TypeError:
		frappe.throw(invalid_message)
	items = list(islice(iterator, max(limit, 0) + 1))
	if len(items) > limit:
		frappe.throw(limit_message)
	return items


def _fetch_rows(
	doctype: str,
	names: set[str],
	fields: Sequence[str],
	*,
	extra_filters: Mapping[str, Any] | None = None,
	respect_permissions: bool = False,
) -> dict[str, Mapping[str, Any]]:
	if not names:
		return {}
	if respect_permissions and not frappe.has_permission(doctype, "read"):
		return {}
	filters = {"name": ["in", sorted(names)], **dict(extra_filters or {})}
	get_rows = frappe.get_list if respect_permissions else frappe.get_all
	rows = get_rows(
		doctype,
		filters=filters,
		fields=list(fields),
		order_by="name asc",
		limit=len(names),
	)
	return {row.name: row for row in rows}


def _assert_related_row_limit(rows: Sequence[Any]) -> None:
	if len(rows) > MAX_RELATED_ROWS:
		frappe.throw(
			_("Correspondence resolution exceeded the related-row limit of {0}.").format(MAX_RELATED_ROWS)
		)


def _address_candidate(address: Mapping[str, Any], provenance: set[tuple[str, str, str]]) -> dict[str, Any]:
	return {
		"name": address["name"],
		"address_type": address.get("address_type"),
		"address_line1": address.get("address_line1"),
		"address_line2": address.get("address_line2"),
		"pincode": address.get("pincode"),
		"city": address.get("city"),
		"county": address.get("county"),
		"state": address.get("state"),
		"country": address.get("country"),
		"is_primary_address": cint(address.get("is_primary_address")),
		"is_shipping_address": cint(address.get("is_shipping_address")),
		"provenance": [
			{"doctype": doctype, "name": name, "via": via} for doctype, name, via in sorted(provenance)
		],
	}


def _select_address(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
	explicit = [
		candidate
		for candidate in candidates
		if any(provenance["via"] != "Dynamic Link" for provenance in candidate["provenance"])
	]
	if len(explicit) == 1:
		return explicit[0]
	if len(explicit) > 1:
		return None
	primary = [candidate for candidate in candidates if candidate["is_primary_address"]]
	if len(primary) == 1:
		return primary[0]
	return candidates[0] if len(candidates) == 1 else None


def _add_issue(issues: list[dict[str, Any]], code: str, **details: Any) -> None:
	if any(issue["code"] == code for issue in issues):
		return
	issues.append({"code": code, **details})
