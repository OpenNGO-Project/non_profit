from __future__ import annotations

import frappe
from frappe import _
from frappe.database.schema import add_column
from frappe.utils import cint, cstr, getdate

OLD_DOCTYPE = "Household Member"
NEW_DOCTYPE = "Household Person"
ROLE_DOCTYPES = ("Member", "Donor")


def execute() -> None:
	legacy_doctype, migration_mode = _legacy_source()
	if not legacy_doctype or not migration_mode:
		return

	rows = _build_migration_plan(legacy_doctype)
	kept_rows, duplicate_names = _validate_and_coalesce_rows(rows)
	if migration_mode == "copy":
		_validate_copy_target(kept_rows)
	_ensure_role_columns()
	_backfill_role_contacts(rows)

	if migration_mode == "rename":
		frappe.rename_doc("DocType", OLD_DOCTYPE, NEW_DOCTYPE, force=True)
		_convert_renamed_rows(kept_rows, duplicate_names)
	elif migration_mode == "finish_rename":
		_convert_renamed_rows(kept_rows, duplicate_names)
	else:
		_copy_orphan_rows(kept_rows)

	frappe.clear_cache(doctype=NEW_DOCTYPE)
	frappe.clear_cache(doctype="Household")


def _convert_renamed_rows(kept_rows: list[frappe._dict], duplicate_names: list[str]) -> None:
	household_person = frappe.qb.DocType(NEW_DOCTYPE)
	for row in kept_rows:
		(
			frappe.qb.update(household_person)
			.set(household_person.link_name, row.contact)
			.set(household_person.is_primary, cint(row.is_primary))
			.where(household_person.name == row.name)
		).run()
	if duplicate_names:
		frappe.qb.from_(household_person).delete().where(household_person.name.isin(duplicate_names)).run()

	if frappe.db.has_column(NEW_DOCTYPE, "link_name") and not frappe.db.has_column(NEW_DOCTYPE, "contact"):
		frappe.db.rename_column(NEW_DOCTYPE, "link_name", "contact")


def _legacy_source() -> tuple[str | None, str | None]:
	old_table_exists = frappe.db.table_exists(OLD_DOCTYPE, cached=False) and frappe.db.has_column(
		OLD_DOCTYPE, "link_name"
	)
	old_doctype_exists = frappe.db.exists("DocType", OLD_DOCTYPE)
	new_doctype_exists = frappe.db.exists("DocType", NEW_DOCTYPE)

	if old_table_exists and old_doctype_exists and not new_doctype_exists:
		return OLD_DOCTYPE, "rename"
	if old_table_exists and _table_has_rows(OLD_DOCTYPE):
		if not new_doctype_exists or not frappe.db.has_column(NEW_DOCTYPE, "contact"):
			frappe.throw(
				_("Orphan Household Member rows exist, but Household Person is not ready for recovery.")
			)
		return OLD_DOCTYPE, "copy"
	if frappe.db.exists("DocType", NEW_DOCTYPE) and frappe.db.has_column(NEW_DOCTYPE, "link_name"):
		# Recovery path if the committed DocType/table rename completed before a prior run stopped.
		return NEW_DOCTYPE, "finish_rename"
	return None, None


def _table_has_rows(doctype: str) -> bool:
	table = frappe.qb.DocType(doctype)
	return bool(frappe.qb.from_(table).select(table.name).limit(1).run())


def _build_migration_plan(legacy_doctype: str) -> list[frappe._dict]:
	legacy = frappe.qb.DocType(legacy_doctype)
	rows = (
		frappe.qb.from_(legacy)
		.select(
			legacy.name,
			legacy.owner,
			legacy.creation,
			legacy.modified,
			legacy.modified_by,
			legacy.docstatus,
			legacy.parent,
			legacy.parentfield,
			legacy.parenttype,
			legacy.idx,
			legacy.link_doctype,
			legacy.link_name,
			legacy.from_date,
			legacy.to_date,
			legacy.is_primary,
		)
		.orderby(legacy.parent)
		.orderby(legacy.idx)
	).run(as_dict=True)

	errors = []
	for row in rows:
		if (
			row.parenttype != "Household"
			or row.parentfield != "members"
			or not frappe.db.exists("Household", row.parent)
		):
			errors.append(
				f"{row.parent or '(no parent)'}, row {row.idx} ({row.name}): "
				+ _("the child row is not attached to Household.members")
			)
			continue
		try:
			row.contact = _resolve_legacy_contact(
				row.link_doctype,
				row.link_name,
				allow_converted_contact=legacy_doctype == NEW_DOCTYPE,
			)
		except frappe.ValidationError as error:
			errors.append(f"{row.parent}, row {row.idx} ({row.name}): {cstr(error)}")
	if errors:
		frappe.throw(
			_("Household Member migration cannot safely identify every person Contact:")
			+ "<br>"
			+ "<br>".join(errors)
		)
	return rows


def _validate_copy_target(rows: list[frappe._dict]) -> None:
	if not rows:
		return
	target = frappe.qb.DocType(NEW_DOCTYPE)
	conflicts = (
		frappe.qb.from_(target)
		.select(target.name)
		.where(target.name.isin([row.name for row in rows]))
		.orderby(target.name)
	).run(pluck=True)
	if conflicts:
		frappe.throw(
			_("Household Person already contains legacy row names: {0}.").format(", ".join(conflicts))
		)


def _copy_orphan_rows(rows: list[frappe._dict]) -> None:
	target = frappe.qb.DocType(NEW_DOCTYPE)
	columns = (
		target.name,
		target.owner,
		target.creation,
		target.modified,
		target.modified_by,
		target.docstatus,
		target.idx,
		target.contact,
		target.from_date,
		target.to_date,
		target.is_primary,
		target.parent,
		target.parentfield,
		target.parenttype,
	)
	for row in rows:
		(
			frappe.qb.into(target)
			.columns(*columns)
			.insert(
				row.name,
				row.owner,
				row.creation,
				row.modified,
				row.modified_by,
				row.docstatus,
				row.idx,
				row.contact,
				row.from_date,
				row.to_date,
				cint(row.is_primary),
				row.parent,
				row.parentfield,
				row.parenttype,
			)
		).run()


def _resolve_legacy_contact(
	role_doctype: str,
	role_name: str,
	*,
	allow_converted_contact: bool = False,
) -> str:
	if role_doctype not in ROLE_DOCTYPES:
		frappe.throw(_("Unsupported household role type {0}.").format(frappe.bold(role_doctype)))
	if not frappe.db.exists(role_doctype, role_name):
		if allow_converted_contact and frappe.db.exists("Contact", role_name):
			return role_name
		frappe.throw(_("{0} {1} no longer exists.").format(role_doctype, frappe.bold(role_name)))

	canonical_contact, subject_type = _role_identity_values(role_doctype, role_name)
	if subject_type and subject_type != "Individual":
		frappe.throw(
			_("{0} {1} is classified as {2}, not an individual.").format(
				role_doctype,
				frappe.bold(role_name),
				frappe.bold(subject_type),
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
	linked_contacts = sorted({name for name in linked_contacts if frappe.db.exists("Contact", name)})

	if canonical_contact:
		if not frappe.db.exists("Contact", canonical_contact):
			frappe.throw(
				_("{0} {1} points to missing Contact {2}.").format(
					role_doctype,
					frappe.bold(role_name),
					frappe.bold(canonical_contact),
				)
			)
		conflicts = [name for name in linked_contacts if name != canonical_contact]
		if conflicts:
			frappe.throw(
				_("{0} {1} has conflicting Contact links: {2}.").format(
					role_doctype,
					frappe.bold(role_name),
					", ".join([canonical_contact, *conflicts]),
				)
			)
		contact = canonical_contact
	elif len(linked_contacts) == 1:
		contact = linked_contacts[0]
	elif not linked_contacts:
		frappe.throw(_("{0} {1} has no linked Contact.").format(role_doctype, frappe.bold(role_name)))
	else:
		frappe.throw(
			_("{0} {1} has multiple linked Contacts: {2}.").format(
				role_doctype,
				frappe.bold(role_name),
				", ".join(linked_contacts),
			)
		)

	if frappe.db.has_column("Contact", "npo_identity_kind"):
		identity_kind = frappe.db.get_value("Contact", contact, "npo_identity_kind")
		if identity_kind and identity_kind != "Person":
			frappe.throw(
				_("Contact {0} is classified as {1}, not a person.").format(
					frappe.bold(contact),
					frappe.bold(identity_kind),
				)
			)
	return contact


def _role_identity_values(role_doctype: str, role_name: str) -> tuple[str | None, str | None]:
	role = frappe.qb.DocType(role_doctype)
	fields = [role.name]
	if frappe.db.has_column(role_doctype, "contact"):
		fields.append(role.contact)
	if frappe.db.has_column(role_doctype, "subject_type"):
		fields.append(role.subject_type)
	row = frappe.qb.from_(role).select(*fields).where(role.name == role_name).limit(1).run(as_dict=True)
	if not row:
		return None, None
	return row[0].get("contact"), row[0].get("subject_type")


def _validate_and_coalesce_rows(
	rows: list[frappe._dict],
) -> tuple[list[frappe._dict], list[str]]:
	errors = []
	role_by_contact: dict[tuple[str, str], str] = {}
	current_by_contact: dict[str, frappe._dict] = {}
	current_primary_by_household: dict[str, frappe._dict] = {}
	duplicates: list[str] = []
	kept_rows: list[frappe._dict] = []

	for row in rows:
		if not row.from_date:
			errors.append(_("Legacy Household row {0} has no From Date.").format(frappe.bold(row.name)))
			continue
		if row.to_date and getdate(row.to_date) < getdate(row.from_date):
			errors.append(
				_("Legacy Household row {0} has a To Date before its From Date.").format(
					frappe.bold(row.name)
				)
			)
			continue

		role_key = (row.link_doctype, row.contact)
		if existing_role := role_by_contact.get(role_key):
			if existing_role != row.link_name:
				errors.append(
					_("Contact {0} maps to multiple {1} roles: {2} and {3}.").format(
						frappe.bold(row.contact),
						row.link_doctype,
						frappe.bold(existing_role),
						frappe.bold(row.link_name),
					)
				)
			else:
				role_by_contact[role_key] = row.link_name
		else:
			role_by_contact[role_key] = row.link_name

		if row.to_date:
			kept_rows.append(row)
			continue

		if existing := current_by_contact.get(row.contact):
			if existing.parent == row.parent and existing.from_date == row.from_date:
				existing.is_primary = max(cint(existing.is_primary), cint(row.is_primary))
				duplicates.append(row.name)
				continue
			errors.append(
				_("Contact {0} has conflicting current Household rows {1} and {2}.").format(
					frappe.bold(row.contact),
					frappe.bold(existing.name),
					frappe.bold(row.name),
				)
			)
			continue

		current_by_contact[row.contact] = row
		kept_rows.append(row)

	for row in kept_rows:
		if row.to_date or not cint(row.is_primary):
			continue
		if existing := current_primary_by_household.get(row.parent):
			errors.append(
				_("Household {0} has multiple current primary rows: {1} and {2}.").format(
					frappe.bold(row.parent),
					frappe.bold(existing.name),
					frappe.bold(row.name),
				)
			)
		else:
			current_primary_by_household[row.parent] = row

	if errors:
		frappe.throw(
			_("Household Member migration found ambiguous identity or date history:")
			+ "<br>"
			+ "<br>".join(errors)
		)
	return kept_rows, duplicates


def _ensure_role_columns() -> None:
	for doctype in ROLE_DOCTYPES:
		if not frappe.db.has_column(doctype, "subject_type"):
			add_column(doctype, "subject_type", "Select")
		if not frappe.db.has_column(doctype, "contact"):
			add_column(doctype, "contact", "Link")


def _backfill_role_contacts(rows: list[frappe._dict]) -> None:
	roles: dict[tuple[str, str], str] = {}
	for row in rows:
		roles[(row.link_doctype, row.link_name)] = row.contact

	for (doctype, name), contact in sorted(roles.items()):
		role = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(role)
			.set(role.subject_type, "Individual")
			.set(role.contact, contact)
			.where(role.name == name)
		).run()
