# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cint, getdate

from non_profit.non_profit.utils import ensure_person_contact


class Household(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self):
		self.validate_person_rows()
		affected_contacts = self.get_affected_contacts()
		self.lock_contacts(affected_contacts)
		self.validate_contact_permissions(affected_contacts)
		for contact in sorted(_contact_names(self.members)):
			ensure_person_contact(contact)
		self.validate_single_current_household()

	def on_update(self):
		self.sync_role_household_links()

	def on_trash(self):
		contacts = _contact_names(self.members)
		self.validate_contact_permissions(contacts)
		self.sync_role_household_links(exclude=self.name)

	def after_delete(self):
		self.sync_role_household_links()

	def validate_person_rows(self) -> None:
		current_contacts = set()
		current_primary = None
		for row in self.members or []:
			if not row.from_date:
				frappe.throw(_("Row {0}: From Date is required.").format(row.idx))
			if row.to_date and getdate(row.to_date) < getdate(row.from_date):
				frappe.throw(_("Row {0}: To Date cannot be before From Date.").format(row.idx))
			if row.to_date:
				continue

			if row.contact in current_contacts:
				frappe.throw(
					_("Row {0}: Contact {1} already has a current row in this Household.").format(
						row.idx,
						frappe.bold(row.contact),
					)
				)
			current_contacts.add(row.contact)

			if row.is_primary:
				if current_primary:
					frappe.throw(
						_("Rows {0} and {1} cannot both be current primary Household members.").format(
							current_primary.idx,
							row.idx,
						)
					)
				current_primary = row

	def get_affected_contacts(self) -> set[str]:
		contacts = _contact_names(self.members)
		if previous := self.get_doc_before_save():
			contacts.update(_contact_names(previous.members))
		return contacts

	def lock_contacts(self, contacts: set[str]) -> None:
		"""Serialize Household changes by canonical person identity."""
		contact = frappe.qb.DocType("Contact")
		for name in sorted(contacts):
			frappe.qb.from_(contact).select(contact.name).where(contact.name == name).for_update().run()

	def validate_contact_permissions(self, contacts: set[str]) -> None:
		if self.flags.ignore_permissions:
			return
		for contact in sorted(contacts):
			frappe.get_doc("Contact", contact).check_permission("write")

	def validate_single_current_household(self):
		"""A Contact can be a current person in one Household only.

		Rows without `to_date` are current; rows of this document are not in the
		database yet on insert and are excluded by name on update, so only
		*other* Households can conflict.
		"""
		for row in self.members or []:
			if row.to_date:
				continue
			others = _get_current_households(row.contact, exclude=self.name, for_update=True)
			if others:
				frappe.throw(
					_("Contact {0} is already a current member of Household {1}.").format(
						frappe.bold(row.contact),
						frappe.bold(others[0]),
					)
				)

	def sync_role_household_links(self, *, exclude: str | None = None) -> None:
		"""Project Contact Household membership onto every linked NPO role."""
		contacts = self.get_affected_contacts() or _contact_names(self.members)
		for contact in sorted(contacts):
			sync_contact_role_households(contact, exclude=exclude)


def get_current_household(contact: str, *, exclude: str | None = None) -> str | None:
	if not contact:
		return None
	households = _get_current_households(contact, exclude=exclude)
	if len(households) > 1:
		frappe.throw(_("Contact {0} has more than one current Household.").format(frappe.bold(contact)))
	return households[0] if households else None


def sync_contact_role_households(contact: str, *, exclude: str | None = None) -> str | None:
	"""Refresh Household projections after a Contact is attached to an NPO role."""
	current_household = get_current_household(contact, exclude=exclude)
	for doctype in ("Member", "Donor"):
		for name in frappe.get_all(doctype, filters={"contact": contact}, pluck="name"):
			if frappe.db.get_value(doctype, name, "household") != current_household:
				frappe.db.set_value(doctype, name, "household", current_household)
			if doctype == "Member":
				frappe.db.set_value(
					"Membership",
					{"member": name},
					"is_household_membership",
					bool(current_household),
				)
	return current_household


def _get_current_households(
	contact: str,
	*,
	exclude: str | None = None,
	for_update: bool = False,
) -> list[str]:
	household_person = frappe.qb.DocType("Household Person")
	query = (
		frappe.qb.from_(household_person)
		.select(household_person.parent)
		.where(household_person.parenttype == "Household")
		.where(household_person.contact == contact)
		.where(household_person.to_date.isnull() | (household_person.to_date == ""))
		.orderby(household_person.creation)
		.limit(2)
	)
	if exclude:
		query = query.where(household_person.parent != exclude)
	if for_update:
		query = query.for_update()
	return query.run(pluck=True)


def add_person_to_household(
	household: str,
	contact: str,
	from_date: str | date,
	to_date: str | date | None = None,
	is_primary: bool = False,
	relationship: str | None = None,
	*,
	ignore_permissions: bool = False,
) -> Household:
	"""Add a dated Contact row and let Household validation enforce person identity."""
	household_doc = frappe.get_doc("Household", household)
	contact_doc = frappe.get_doc("Contact", contact)
	if not ignore_permissions:
		household_doc.check_permission("write")
		contact_doc.check_permission("write")
	household_doc.append(
		"members",
		{
			"contact": contact,
			"relationship": relationship,
			"from_date": from_date,
			"to_date": to_date,
			"is_primary": cint(is_primary),
		},
	)
	household_doc.save(ignore_permissions=ignore_permissions)
	return household_doc


def _contact_names(rows) -> set[str]:
	return {row.contact for row in rows or [] if row.contact}
