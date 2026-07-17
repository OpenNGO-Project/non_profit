# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cint, getdate

HOUSEHOLD_PARTY_DOCTYPES = ("Member", "Donor")


class Household(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def validate(self):
		self.validate_member_rows()
		affected_parties = self.get_affected_parties()
		self.lock_parties(affected_parties)
		self.validate_party_permissions(affected_parties)
		self.validate_single_current_household()

	def on_update(self):
		self.sync_party_household_links()

	def on_trash(self):
		# Clear derived links before Frappe checks whether they block deletion.
		for doctype, name in sorted(_party_keys(self.members)):
			if not frappe.db.exists(doctype, name):
				continue
			if frappe.db.get_value(doctype, name, "household") == self.name:
				frappe.db.set_value(doctype, name, "household", None)
			if doctype == "Member":
				self.refresh_membership_household_flag(name)

	def after_delete(self):
		self.sync_party_household_links()

	def validate_member_rows(self) -> None:
		current_parties = set()
		current_primary = None
		for row in self.members or []:
			if not row.from_date:
				frappe.throw(_("Row {0}: From Date is required.").format(row.idx))
			if row.to_date and getdate(row.to_date) < getdate(row.from_date):
				frappe.throw(_("Row {0}: To Date cannot be before From Date.").format(row.idx))
			if row.to_date:
				continue

			party = (row.link_doctype, row.link_name)
			if party in current_parties:
				frappe.throw(
					_("Row {0}: {1} {2} already has a current row in this Household.").format(
						row.idx,
						row.link_doctype,
						frappe.bold(row.link_name),
					)
				)
			current_parties.add(party)

			if row.is_primary:
				if current_primary:
					frappe.throw(
						_("Rows {0} and {1} cannot both be current primary Household members.").format(
							current_primary.idx,
							row.idx,
						)
					)
				current_primary = row

	def get_affected_parties(self) -> set[tuple[str, str]]:
		parties = _party_keys(self.members)
		if previous := self.get_doc_before_save():
			parties.update(_party_keys(previous.members))
		return parties

	def lock_parties(self, parties: set[tuple[str, str]]) -> None:
		"""Serialize Household changes per party to narrow concurrent-current races."""
		for doctype, name in sorted(parties):
			if doctype not in HOUSEHOLD_PARTY_DOCTYPES or not name:
				continue
			party = frappe.qb.DocType(doctype)
			frappe.qb.from_(party).select(party.name).where(party.name == name).for_update().run()

	def validate_party_permissions(self, parties: set[tuple[str, str]]) -> None:
		if self.flags.ignore_permissions:
			return
		for doctype, name in sorted(parties):
			if doctype in HOUSEHOLD_PARTY_DOCTYPES and name:
				frappe.get_doc(doctype, name).check_permission("write")

	def validate_single_current_household(self):
		"""A Member/Donor can be a current member of one household only.

		Rows without `to_date` are current; rows of this document are not in the
		database yet on insert and are excluded by name on update, so only
		*other* Households can conflict.
		"""
		for row in self.members or []:
			if row.to_date:
				continue
			others = _get_current_households(
				row.link_doctype,
				row.link_name,
				exclude=self.name,
				for_update=True,
			)
			if others:
				frappe.throw(
					_("{0} {1} is already a current member of Household {2}.").format(
						row.link_doctype,
						frappe.bold(row.link_name),
						frappe.bold(others[0]),
					)
				)

	def sync_party_household_links(self):
		"""Reconcile current links for both present rows and rows removed or retargeted."""
		for doctype, name in sorted(self.get_affected_parties() or _party_keys(self.members)):
			if doctype not in HOUSEHOLD_PARTY_DOCTYPES or not frappe.db.exists(doctype, name):
				continue
			current_household = get_current_household(doctype, name)
			if frappe.db.get_value(doctype, name, "household") != current_household:
				frappe.db.set_value(doctype, name, "household", current_household)
			if doctype == "Member":
				self.refresh_membership_household_flag(name)

	def refresh_membership_household_flag(self, member: str):
		in_household = bool(frappe.db.get_value("Member", member, "household"))
		frappe.db.set_value(
			"Membership",
			{"member": member},
			"is_household_membership",
			in_household,
		)


def get_current_household(link_doctype: str, link_name: str) -> str | None:
	if link_doctype not in HOUSEHOLD_PARTY_DOCTYPES or not link_name:
		return None
	households = _get_current_households(link_doctype, link_name)
	if len(households) > 1:
		frappe.throw(
			_("{0} {1} has more than one current Household.").format(
				link_doctype,
				frappe.bold(link_name),
			)
		)
	return households[0] if households else None


def _get_current_households(
	link_doctype: str,
	link_name: str,
	*,
	exclude: str | None = None,
	for_update: bool = False,
) -> list[str]:
	household_member = frappe.qb.DocType("Household Member")
	query = (
		frappe.qb.from_(household_member)
		.select(household_member.parent)
		.where(household_member.parenttype == "Household")
		.where(household_member.link_doctype == link_doctype)
		.where(household_member.link_name == link_name)
		.where(household_member.to_date.isnull() | (household_member.to_date == ""))
		.orderby(household_member.creation)
		.limit(2)
	)
	if exclude:
		query = query.where(household_member.parent != exclude)
	if for_update:
		query = query.for_update()
	return query.run(pluck=True)


def add_member_to_household(
	household: str,
	member: str,
	from_date: str | date,
	to_date: str | date | None = None,
	is_primary: bool = False,
	*,
	ignore_permissions: bool = False,
) -> Household:
	"""Add a dated Member row and let Household validation and sync enforce invariants."""
	household_doc = frappe.get_doc("Household", household)
	member_doc = frappe.get_doc("Member", member)
	if not ignore_permissions:
		household_doc.check_permission("write")
		member_doc.check_permission("write")
	household_doc.append(
		"members",
		{
			"link_doctype": "Member",
			"link_name": member,
			"from_date": from_date,
			"to_date": to_date,
			"is_primary": cint(is_primary),
		},
	)
	household_doc.save(ignore_permissions=ignore_permissions)
	return household_doc


def _party_keys(rows) -> set[tuple[str, str]]:
	return {
		(row.link_doctype, row.link_name)
		for row in rows or []
		if row.link_doctype in HOUSEHOLD_PARTY_DOCTYPES and row.link_name
	}
