import frappe

from non_profit.setup import make_custom_fields


def execute() -> None:
	if not frappe.db.exists("DocType", "Household Person"):
		return

	make_custom_fields()
	household_person = frappe.qb.DocType("Household Person")
	contacts = (
		frappe.qb.from_(household_person)
		.select(household_person.contact)
		.where(household_person.parenttype == "Household")
		.where(household_person.contact.notnull())
		.distinct()
	).run(pluck=True)

	from non_profit.non_profit.doctype.household.household import sync_contact_role_households
	from non_profit.non_profit.utils import ensure_person_contact

	for contact in sorted(filter(None, contacts)):
		ensure_person_contact(contact)
		sync_contact_role_households(contact)
