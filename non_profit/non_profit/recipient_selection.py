from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, getdate

from non_profit.non_profit.correspondence import (
	MAX_RELATED_ROWS,
	MAX_SOURCE_REFERENCES,
	get_correspondence_profiles,
)

SELECTION_DOCTYPE = "NPO Recipient Selection"
PROVIDER_KEY = "npo_recipient_selection"
CONFIGURATION_VERSION = 1
PREVIEW_LIMIT = 50
MAX_SELECTION_SOURCE_ROWS = 10_000

CHANNEL_FIELDS = {
	"newsletter": "available_for_newsletter",
	"direct_mail": "available_for_direct_mail",
}
RECIPIENT_SELECTION_CHANNEL_HOOK = "non_profit_recipient_selection_channels"
CONFIGURATION_FIELDS = (
	"enabled",
	"available_for_newsletter",
	"available_for_direct_mail",
	"include_contacts",
	"contact_tag",
	"include_members",
	"membership_type",
	"membership_status",
	"membership_active_on",
	"include_donors",
	"donor_type",
)
CHECK_FIELDS = {
	"enabled",
	"available_for_newsletter",
	"available_for_direct_mail",
	"include_contacts",
	"include_members",
	"include_donors",
}
SUPPORTED_NEWSLETTER_LANGUAGES = {"de", "en", "fr", "it"}


@dataclass
class _RecipientCandidate:
	subject_type: str
	subject_name: str
	label: str
	contacts: set[str] = field(default_factory=set)
	members: set[str] = field(default_factory=set)
	donors: set[str] = field(default_factory=set)
	customers: set[str] = field(default_factory=set)

	@property
	def key(self) -> tuple[str, str]:
		return self.subject_type, self.subject_name

	@property
	def related_count(self) -> int:
		return len(self.contacts) + len(self.members) + len(self.donors) + len(self.customers)

	def correspondence_reference(self) -> dict[str, Any]:
		return {
			"canonical_subject_type": self.subject_type,
			"canonical_subject": self.subject_name,
			"contacts": sorted(self.contacts),
			"members": sorted(self.members),
			"donors": sorted(self.donors),
			"customers": sorted(self.customers),
		}


def get_channel_fields() -> dict[str, str]:
	"""Channel key → availability fieldname on ``NPO Recipient Selection``.

	The two built-in channels are literals; additional channels register
	through the neutral ``non_profit_recipient_selection_channels`` hook
	(each entry a dotted callable returning ``{"key", "fieldname", "label"}``
	or a list of such dicts). Registered channel availability fields are
	deliberately **not** part of the configuration snapshot/fingerprint:
	availability gates which channel may consume a selection, not who the
	audience is (the built-ins remain in the snapshot for compatibility).
	"""
	fields = dict(CHANNEL_FIELDS)
	for provider in frappe.get_hooks(RECIPIENT_SELECTION_CHANNEL_HOOK) or []:
		registered = frappe.get_attr(provider)()
		if isinstance(registered, dict):
			registered = [registered]
		if not isinstance(registered, list):
			continue
		for channel in registered:
			if not isinstance(channel, dict):
				continue
			key = cstr(channel.get("key")).strip().lower()
			fieldname = cstr(channel.get("fieldname")).strip()
			if not key or not fieldname or key in fields:
				continue
			fields[key] = fieldname
	return fields


def validate_recipient_selection(selection: Document) -> None:
	if not any(cint(selection.get(fieldname)) for fieldname in get_channel_fields().values()):
		frappe.throw(_("Enable at least one delivery channel."))
	if not any(
		cint(selection.get(fieldname))
		for fieldname in ("include_contacts", "include_members", "include_donors")
	):
		frappe.throw(_("Enable at least one recipient source."))
	if cint(selection.get("include_members")) and not selection.get("membership_active_on"):
		frappe.throw(_("Membership Active On is required when Members are included."))


def evaluate_recipient_selection(selection: Document) -> list[dict[str, Any]]:
	"""Evaluate one in-memory selection without applying an enabled/channel gate."""
	validate_recipient_selection(selection)
	_require_source_permissions(selection)
	rows: list[dict[str, Any]] = []
	if cint(selection.get("include_contacts")):
		rows.extend(_contact_source_rows(selection))
		_assert_source_row_limit(rows)
	if cint(selection.get("include_members")):
		rows.extend(_member_source_rows(selection))
		_assert_source_row_limit(rows)
	if cint(selection.get("include_donors")):
		rows.extend(_donor_source_rows(selection))
		_assert_source_row_limit(rows)
	rows = _filter_visible_canonical_rows(rows)
	return sorted(rows, key=_source_row_sort_key)


def get_recipient_selection_rows(
	selection: Document | str,
	channel: str,
) -> list[dict[str, Any]]:
	"""Return deterministic Direct-Mail-compatible source rows for a saved selection.

	A name is permission-checked before its configuration or source data is read.
	Document callers are responsible for authorizing that already-loaded document.
	"""
	selection_doc = _selection_document(selection)
	_validate_enabled_channel(selection_doc, channel)
	return evaluate_recipient_selection(selection_doc)


def get_recipient_selection_configuration(selection: Document | str) -> dict[str, Any]:
	"""Return stable JSON-compatible criteria for consumer fingerprinting."""
	selection_doc = _selection_document(selection)
	configuration: dict[str, Any] = {
		"configuration_version": CONFIGURATION_VERSION,
		"selection": cstr(selection_doc.get("name")),
		"selection_name": cstr(selection_doc.get("selection_name")),
	}
	for fieldname in CONFIGURATION_FIELDS:
		value = selection_doc.get(fieldname)
		configuration[fieldname] = cint(value) if fieldname in CHECK_FIELDS else cstr(value)
	return configuration


def count_canonical_candidates(rows: list[dict[str, Any]]) -> int:
	return len(_merge_candidates(rows))


def newsletter_audience_provider() -> dict[str, str]:
	return {
		"key": PROVIDER_KEY,
		"label": _("NPO Recipient Selection"),
		"list_sources": "non_profit.non_profit.recipient_selection.newsletter_selection_sources",
		"get_members": "non_profit.non_profit.recipient_selection.newsletter_selection_members",
	}


def newsletter_selection_sources() -> list[dict[str, Any]]:
	if not frappe.has_permission(SELECTION_DOCTYPE, "read"):
		return []
	rows = frappe.get_list(
		SELECTION_DOCTYPE,
		filters={"enabled": 1, "available_for_newsletter": 1},
		fields=["name", "selection_name", "candidate_count"],
		order_by="selection_name asc, name asc",
		limit=0,
	)
	return [
		{
			"value": row.name,
			"label": row.selection_name or row.name,
			"count": cint(row.candidate_count),
		}
		for row in rows
	]


def newsletter_selection_members(source: str) -> list[dict[str, str]]:
	rows = get_recipient_selection_rows(source, "newsletter")
	return _newsletter_members(_merge_candidates(rows))


def newsletter_members_from_donors(donor_names: list[str] | Any) -> list[dict[str, str]]:
	"""Resolve explicit Donors through the canonical newsletter delivery path."""
	return _newsletter_members(_merge_candidates(donor_source_rows(donor_names)))


@frappe.whitelist(methods=["GET"])
def preview_recipient_selection(selection: str) -> dict[str, Any]:
	"""Return a read-only, bounded preview without exposing postal addresses."""
	selection_doc = _selection_document(selection)
	rows = evaluate_recipient_selection(selection_doc)
	candidates = _merge_candidates(rows)
	preview_candidates = candidates[:PREVIEW_LIMIT]
	preview_rows = []
	for candidate, profile, email_data in _candidate_delivery_rows(preview_candidates):
		preview_rows.append(
			{
				"subject_type": candidate.subject_type,
				"subject_name": candidate.subject_name,
				"label": candidate.label,
				"email": email_data["email"],
				"language": email_data["language"],
				"postal_ready": _postal_ready(profile),
			}
		)
	return {"total": len(candidates), "rows": preview_rows}


def _selection_document(selection: Document | str) -> Document:
	if isinstance(selection, str):
		doc = frappe.get_doc(SELECTION_DOCTYPE, selection)
		doc.check_permission("read")
		return doc
	if selection.get("doctype") != SELECTION_DOCTYPE:
		frappe.throw(_("Expected an NPO Recipient Selection document."))
	return selection


def _validate_enabled_channel(selection: Document, channel: str) -> None:
	channel = cstr(channel).strip().lower()
	channel_fields = get_channel_fields()
	if channel not in channel_fields:
		frappe.throw(
			_("Recipient selection channel must be one of: {0}.").format(
				", ".join(sorted(channel_fields))
			)
		)
	if not cint(selection.get("enabled")):
		frappe.throw(_("NPO Recipient Selection {0} is disabled.").format(selection.name))
	if not cint(selection.get(channel_fields[channel])):
		frappe.throw(
			_("NPO Recipient Selection {0} is not available for {1}.").format(
				selection.name, channel.replace("_", " ")
			)
		)


def _require_source_permissions(selection: Document) -> None:
	required = []
	if cint(selection.get("include_contacts")):
		required.append("Contact")
	if cint(selection.get("include_members")):
		required.extend(("Member", "Membership"))
	if cint(selection.get("include_donors")):
		required.append("Donor")
	missing = [doctype for doctype in required if not frappe.has_permission(doctype, "read")]
	if missing:
		frappe.throw(
			_("Not permitted to read recipient source data for: {0}").format(", ".join(missing)),
			frappe.PermissionError,
		)


def _contact_source_rows(selection: Document) -> list[dict[str, Any]]:
	contact_names = None
	if selection.get("contact_tag"):
		contact_names = sorted(
			set(
				frappe.get_all(
					"Tag Link",
					filters={
						"document_type": "Contact",
						"tag": selection.contact_tag,
					},
					pluck="document_name",
					order_by="document_name asc",
					limit=MAX_SELECTION_SOURCE_ROWS + 1,
				)
			)
		)
		_assert_source_row_limit(contact_names)
		if not contact_names:
			return []

	filters = {"name": ["in", contact_names]} if contact_names is not None else None
	rows = frappe.get_list(
		"Contact",
		filters=filters,
		or_filters=[
			["Contact", "npo_identity_kind", "is", "not set"],
			["Contact", "npo_identity_kind", "=", ""],
			["Contact", "npo_identity_kind", "=", "Person"],
		],
		fields=["name", "full_name", "first_name", "last_name"],
		order_by="name asc",
		limit=MAX_SELECTION_SOURCE_ROWS + 1,
	)
	_assert_source_row_limit(rows)
	return [
		{
			"canonical_subject_type": "Contact",
			"canonical_subject": row.name,
			"label": _contact_label(row),
			"source_doctype": "Contact",
			"source_name": row.name,
			"contact": row.name,
			"identity_name": _contact_label(row),
		}
		for row in rows
	]


def _member_source_rows(selection: Document) -> list[dict[str, Any]]:
	active_on = getdate(selection.membership_active_on)
	filters: dict[str, Any] = {"from_date": ["<=", active_on]}
	if selection.get("membership_status"):
		filters["membership_status"] = selection.membership_status
	if selection.get("membership_type"):
		filters["membership_type"] = selection.membership_type
	memberships = frappe.get_list(
		"Membership",
		filters=filters,
		or_filters=[
			["Membership", "to_date", "is", "not set"],
			["Membership", "to_date", ">=", active_on],
		],
		fields=["name", "member"],
		order_by="member asc, name asc",
		limit=MAX_SELECTION_SOURCE_ROWS + 1,
	)
	_assert_source_row_limit(memberships)
	member_names = sorted({row.member for row in memberships if row.member})
	members = {
		row.name: row
		for row in frappe.get_list(
			"Member",
			filters={"name": ["in", member_names]},
			fields=["name", "member_name", "subject_type", "contact", "customer"],
			order_by="name asc",
			limit=MAX_SELECTION_SOURCE_ROWS + 1,
		)
	}

	result = []
	for membership in memberships:
		row = members.get(membership.member)
		if not row:
			continue
		subject_type, subject_name = _member_canonical_subject(row)
		if not subject_name:
			continue
		result.append(
			{
				"canonical_subject_type": subject_type,
				"canonical_subject": subject_name,
				"label": row.member_name or row.member,
				"source_doctype": "Member",
				"source_name": row.member,
				"membership": membership.name,
				"contact": row.contact,
				"member": row.member,
				"customer": row.customer,
				"identity_name": row.member_name,
			}
		)
	return result


def _donor_source_rows(selection: Document) -> list[dict[str, Any]]:
	filters = {}
	if selection.get("donor_type"):
		filters["donor_type"] = selection.donor_type
	rows = frappe.get_list(
		"Donor",
		filters=filters,
		fields=[
			"name",
			"donor_name",
			"donor_type",
			"subject_type",
			"contact",
			"customer",
			"subject_household",
		],
		order_by="name asc",
		limit=MAX_SELECTION_SOURCE_ROWS + 1,
	)
	_assert_source_row_limit(rows)
	return donor_source_rows(row.name for row in rows)


def donor_source_rows(donor_names: list[str] | Any) -> list[dict[str, Any]]:
	"""Return canonical source rows for explicit Donor names.

	This is the shared helper used by NPO selections and optional audience apps:
	permission-aware callers fetch/filter Donor rows themselves, then use this
	single canonicalization rule instead of copying the Contact/Customer/
	Household mapping.
	"""
	names = [cstr(name).strip() for name in dict.fromkeys(donor_names or []) if cstr(name).strip()]
	if not names:
		return []
	rows = _permission_visible_row_map(
		"Donor",
		set(names),
		["name", "donor_name", "subject_type", "contact", "customer", "subject_household"],
	)
	result = []
	for name in names:
		row = rows.get(name)
		if not row:
			continue
		subject_type, subject_name = _donor_canonical_subject(row)
		if not subject_name:
			continue
		result.append(
			{
				"canonical_subject_type": subject_type,
				"canonical_subject": subject_name,
				"label": row.donor_name or row.name,
				"source_doctype": "Donor",
				"source_name": row.name,
				"contact": row.contact,
				"customer": row.customer,
				"donor": row.name,
				"identity_name": row.donor_name,
			}
		)
	return _filter_visible_canonical_rows(result)


def _member_canonical_subject(member: Any) -> tuple[str, str]:
	if member.contact:
		return "Contact", member.contact
	subject_type = cstr(member.subject_type).strip()
	if subject_type == "Organization" and member.customer:
		return "Customer", member.customer
	if not subject_type and member.customer:
		return "Customer", member.customer
	return "", ""


def _donor_canonical_subject(donor: Any) -> tuple[str, str]:
	subject_type = cstr(donor.subject_type).strip()
	if (
		subject_type == "Household" or (not subject_type and donor.subject_household)
	) and donor.subject_household:
		return "Household", donor.subject_household
	if subject_type == "Organization" and donor.customer:
		return "Customer", donor.customer
	if subject_type in {"", "Individual"} and donor.contact:
		return "Contact", donor.contact
	if not subject_type and donor.customer:
		return "Customer", donor.customer
	return "", ""


def _filter_visible_canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	references: dict[str, set[str]] = {doctype: set() for doctype in ("Contact", "Customer", "Household")}
	for row in rows:
		doctype = cstr(row.get("canonical_subject_type")).strip()
		name = cstr(row.get("canonical_subject")).strip()
		if doctype in references and name:
			references[doctype].add(name)
		for fieldname, related_doctype in (("contact", "Contact"), ("customer", "Customer")):
			if related_name := cstr(row.get(fieldname)).strip():
				references[related_doctype].add(related_name)

	visible: dict[str, set[str]] = {}
	for doctype, names in references.items():
		if not names or not frappe.has_permission(doctype, "read"):
			visible[doctype] = set()
			continue
		fields = ["name", "npo_identity_kind"] if doctype == "Contact" else ["name"]
		visible_rows = frappe.get_list(
			doctype,
			filters={"name": ["in", sorted(names)]},
			fields=fields,
			order_by="name asc",
			limit=MAX_SELECTION_SOURCE_ROWS + 1,
		)
		visible[doctype] = {
			row.name
			for row in visible_rows
			if doctype != "Contact" or row.npo_identity_kind != "Generic Endpoint"
		}
	filtered = []
	for row in rows:
		subject_type = cstr(row.get("canonical_subject_type")).strip()
		subject_name = cstr(row.get("canonical_subject")).strip()
		if subject_name not in visible.get(subject_type, set()):
			continue
		safe_row = dict(row)
		for fieldname, related_doctype in (("contact", "Contact"), ("customer", "Customer")):
			related_name = cstr(safe_row.get(fieldname)).strip()
			if related_name and related_name not in visible[related_doctype]:
				safe_row[fieldname] = None
		filtered.append(safe_row)
	return filtered


def _assert_source_row_limit(rows: list[Any]) -> None:
	if len(rows) > MAX_SELECTION_SOURCE_ROWS:
		frappe.throw(
			_("Recipient selection exceeds the {0}-source-row limit. Narrow its filters.").format(
				MAX_SELECTION_SOURCE_ROWS
			)
		)


def _source_row_sort_key(row: dict[str, Any]) -> tuple[str, ...]:
	return (
		cstr(row.get("canonical_subject_type")),
		cstr(row.get("canonical_subject")),
		cstr(row.get("source_doctype")),
		cstr(row.get("source_name")),
		cstr(row.get("membership")),
	)


def _contact_label(row: Any) -> str:
	return (
		cstr(row.get("full_name")).strip()
		or " ".join(
			part for part in (cstr(row.get("first_name")).strip(), cstr(row.get("last_name")).strip()) if part
		)
		or cstr(row.get("name"))
	)


def _merge_candidates(rows: list[dict[str, Any]]) -> list[_RecipientCandidate]:
	candidates: dict[tuple[str, str], _RecipientCandidate] = {}
	for row in sorted(rows, key=_source_row_sort_key):
		subject_type = cstr(row.get("canonical_subject_type")).strip()
		subject_name = cstr(row.get("canonical_subject")).strip()
		if not subject_type or not subject_name:
			continue
		key = (subject_type, subject_name)
		candidate = candidates.setdefault(
			key,
			_RecipientCandidate(
				subject_type=subject_type,
				subject_name=subject_name,
				label=cstr(row.get("label")).strip() or subject_name,
			),
		)
		for fieldname, target in (
			("contact", candidate.contacts),
			("member", candidate.members),
			("donor", candidate.donors),
			("customer", candidate.customers),
		):
			if value := cstr(row.get(fieldname)).strip():
				target.add(value)
		if subject_type == "Contact":
			candidate.contacts.add(subject_name)
		elif subject_type == "Customer":
			candidate.customers.add(subject_name)
	return [candidates[key] for key in sorted(candidates)]


def _newsletter_members(candidates: list[_RecipientCandidate]) -> list[dict[str, str]]:
	"""Return at most one import row per canonical candidate.

	A candidate that resolves to no reachable address keeps a row with an empty
	``email`` so the consuming import can report it as skipped-without-email
	instead of silently losing it.
	"""
	members = []
	seen_emails: set[str] = set()
	for _candidate, _profile, email_data in _candidate_delivery_rows(candidates):
		email = email_data["email"]
		if not email:
			members.append(email_data)
			continue
		email_key = email.casefold()
		if email_key in seen_emails:
			continue
		seen_emails.add(email_key)
		members.append(email_data)
	return members


def _candidate_delivery_rows(candidates: list[_RecipientCandidate]):
	for candidate_batch in _profile_batches(candidates):
		profiles = get_correspondence_profiles(
			[candidate.correspondence_reference() for candidate in candidate_batch],
			respect_permissions=True,
		)
		email_context = _load_email_context(candidate_batch, profiles)
		for candidate, profile in zip(candidate_batch, profiles, strict=True):
			yield candidate, profile, _candidate_email_data(candidate, profile, email_context)


def _profile_batches(candidates: list[_RecipientCandidate]) -> list[list[_RecipientCandidate]]:
	batches: list[list[_RecipientCandidate]] = []
	batch: list[_RecipientCandidate] = []
	related_count = 0
	for candidate in candidates:
		if candidate.related_count > MAX_RELATED_ROWS:
			frappe.throw(
				_("Recipient {0} has too many related identities to resolve.").format(candidate.label)
			)
		if batch and (
			len(batch) >= MAX_SOURCE_REFERENCES or related_count + candidate.related_count > MAX_RELATED_ROWS
		):
			batches.append(batch)
			batch = []
			related_count = 0
		batch.append(candidate)
		related_count += candidate.related_count
	if batch:
		batches.append(batch)
	return batches


def _load_email_context(
	candidates: list[_RecipientCandidate],
	profiles: list[dict[str, Any]],
) -> dict[str, Any]:
	customer_names = set()
	contact_names = set()
	for candidate in candidates:
		contact_names.update(candidate.contacts)
		if candidate.subject_type == "Customer":
			customer_names.add(candidate.subject_name)
		elif candidate.subject_type == "Contact":
			contact_names.add(candidate.subject_name)
	for profile in profiles:
		contact_names.update(
			person.get("contact") for person in profile.get("people", []) if person.get("contact")
		)

	customers = _permission_visible_row_map(
		"Customer",
		customer_names,
		["name", "email_id", "customer_primary_contact"],
	)
	contact_names.update(
		row.customer_primary_contact for row in customers.values() if row.customer_primary_contact
	)
	contacts = _permission_visible_row_map(
		"Contact",
		contact_names,
		[
			"name",
			"email_id",
			"first_name",
			"last_name",
			"unsubscribed",
			"npo_identity_kind",
		],
	)
	return {
		"customers": customers,
		"contacts": contacts,
	}


def _permission_visible_row_map(
	doctype: str,
	names: set[str],
	fields: list[str],
) -> dict[str, Any]:
	if not names or not frappe.has_permission(doctype, "read"):
		return {}
	rows = {}
	ordered_names = sorted(names)
	for start in range(0, len(ordered_names), MAX_SOURCE_REFERENCES):
		batch = ordered_names[start : start + MAX_SOURCE_REFERENCES]
		for row in frappe.get_list(
			doctype,
			filters={"name": ["in", batch]},
			fields=fields,
			order_by="name asc",
			limit=len(batch),
		):
			rows[row.name] = row
	return rows


def _candidate_email_data(
	candidate: _RecipientCandidate,
	profile: dict[str, Any],
	context: dict[str, Any],
) -> dict[str, str]:
	email, contact_name = _candidate_email(candidate, profile, context)
	contact = context["contacts"].get(contact_name) or frappe._dict()
	language = _newsletter_language(profile.get("language"))
	addressee = cstr(profile.get("addressee")).strip() or candidate.label
	return {
		"email": email,
		"contact": contact_name or "",
		"first_name": cstr(contact.get("first_name")).strip(),
		"last_name": cstr(contact.get("last_name")).strip(),
		"salutation": _complete_neutral_salutation(
			addressee, language, kind=_addressee_kind(profile.get("subject_type"))
		),
		"language": language,
	}


def _candidate_email(
	candidate: _RecipientCandidate,
	profile: dict[str, Any],
	context: dict[str, Any],
) -> tuple[str, str]:
	blocked_emails: set[str] = set()
	if candidate.subject_type == "Customer":
		customer = context["customers"].get(candidate.subject_name)
		if customer:
			email = cstr(customer.email_id).strip()
			if email:
				contact_order = list(
					dict.fromkeys(
						[
							cstr(customer.customer_primary_contact).strip(),
							*_candidate_contact_order(candidate, profile),
						]
					)
				)
				contact_order = [name for name in contact_order if name]
				matching_contacts = []
				missing_contact = bool(profile.get("inaccessible_contacts"))
				for contact_name in contact_order:
					contact = context["contacts"].get(contact_name)
					if not contact:
						missing_contact = True
						continue
					if cstr(contact.email_id).strip().casefold() == email.casefold():
						matching_contacts.append((contact_name, contact))
				customer_email_blocked = missing_contact or any(
					cint(contact.unsubscribed) for _name, contact in matching_contacts
				)
				if not customer_email_blocked:
					matching_people = [
						(name, contact)
						for name, contact in matching_contacts
						if contact.npo_identity_kind != "Generic Endpoint"
					]
					return email, matching_people[0][0] if matching_people else ""
				blocked_emails.add(email.casefold())

	for contact_name in _candidate_contact_order(candidate, profile):
		contact = context["contacts"].get(contact_name)
		if not contact or contact.npo_identity_kind == "Generic Endpoint" or cint(contact.unsubscribed):
			continue
		email = cstr(contact.email_id).strip()
		if email and email.casefold() not in blocked_emails:
			return email, contact_name
	return "", ""


def _candidate_contact_order(
	candidate: _RecipientCandidate,
	profile: dict[str, Any],
) -> list[str]:
	contacts = []
	if candidate.subject_type == "Contact":
		contacts.append(candidate.subject_name)
	contacts.extend(person.get("contact") for person in profile.get("people", []) if person.get("contact"))
	contacts.extend(sorted(candidate.contacts))
	return list(dict.fromkeys(contacts))


def _newsletter_language(value: Any) -> str:
	language = cstr(value).strip().lower().replace("_", "-").split("-", 1)[0]
	return language if language in SUPPORTED_NEWSLETTER_LANGUAGES else ""


# Local implementation of the neutral greeting contract. Public tests pin the
# supported languages, identity kinds, fallback, and punctuation behavior.
_NEUTRAL_GREETINGS = {
	"de": ("Guten Tag", ""),
	"fr": ("Bonjour", ","),
	"it": ("Buongiorno", ","),
	"en": ("Dear", ","),
}

# A legal entity is never greeted by name; the addressee is dropped entirely.
_ORGANIZATION_GREETINGS = {
	"de": "Sehr geehrte Damen und Herren,",
	"fr": "Madame, Monsieur,",
	"it": "Gentili Signore e Signori,",
	"en": "Dear Sir or Madam,",
}

_SALUTATION_FALLBACK_LANGUAGE = "de"

_ADDRESSEE_KINDS = ("person", "household", "organization")


def _complete_neutral_salutation(addressee: str, language: str, *, kind: str) -> str:
	"""Greeting for an addressee with no separable name parts.

	``kind`` "household"/"person" are greeted by name; "organization" is not,
	because addressing a company by its own name reads as addressing a person.
	Required, with no default, so a new caller cannot silently greet a company
	by its own name — the defect this argument exists to prevent. An unknown
	value throws for the same reason: a misspelled "organisation" must not
	silently fall into greet-by-name.
	"""
	if kind not in _ADDRESSEE_KINDS:
		raise ValueError(f"unknown addressee kind {kind!r}; expected one of {_ADDRESSEE_KINDS}")
	# `.get()` rather than `[...]`: an unsupported language must fall back, not
	# raise mid-campaign. Newsletter languages are already normalized, but this
	# helper is also reachable with a raw stored value.
	language = language or _SALUTATION_FALLBACK_LANGUAGE
	if kind == "organization":
		return _ORGANIZATION_GREETINGS.get(language, _ORGANIZATION_GREETINGS[_SALUTATION_FALLBACK_LANGUAGE])
	greeting, punctuation = _NEUTRAL_GREETINGS.get(
		language, _NEUTRAL_GREETINGS[_SALUTATION_FALLBACK_LANGUAGE]
	)
	text = cstr(addressee).strip()
	# Without a name there is nothing to punctuate: "Dear ," was the old output.
	if not text:
		return greeting
	return " ".join(f"{greeting} {text}{punctuation}".split()).replace(" ,", ",")


def _addressee_kind(subject_type: Any) -> str:
	"""Map a correspondence subject type onto a salutation addressee kind."""
	return "organization" if cstr(subject_type).strip() == "Organization" else "person"


def _postal_ready(profile: dict[str, Any]) -> bool:
	address = profile.get("address") or {}
	return all(
		cstr(address.get(fieldname)).strip() for fieldname in ("address_line1", "pincode", "city", "country")
	)
