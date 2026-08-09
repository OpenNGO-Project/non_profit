# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Materialized Household giving across current people and joint gifts."""

import frappe
from frappe.utils import flt, getdate

HOUSEHOLD_BATCH_SIZE = 100
HOUSEHOLD_GIVING_FIELDS = (
	"giving_currency",
	"giving_currency_conflict",
	"total_lifetime_amount",
	"gift_count",
	"first_gift_date",
	"last_gift_date",
	"last_gift_amount",
	"largest_gift_amount",
)


def recompute_household_giving(household: str) -> None:
	"""Rebuild one Household from a deduplicated Donor set.

	The set contains Donors backed by current Household people plus canonical
	Household-subject Donors. A Donor satisfying both paths is counted once.
	Only submitted, paid Donations qualify, matching Donor roll-ups.
	"""
	if not household or not frappe.db.get_value("Household", household, "name", for_update=True):
		return
	donor_names = household_donor_names(household, for_update=True)
	donations = []
	if donor_names:
		donation = frappe.qb.DocType("Donation")
		donations = (
			frappe.qb.from_(donation)
			.select(
				donation.name,
				donation.amount,
				donation.date,
				donation.company,
				donation.modified,
			)
			.where(donation.donor.isin(sorted(donor_names)))
			.where(donation.docstatus == 1)
			.where(donation.paid == 1)
			.orderby(donation.name)
		).run(as_dict=True)

	companies = sorted({row.company for row in donations if row.company})
	currency_by_company = (
		{
			row.name: row.default_currency
			for row in frappe.get_all(
				"Company",
				filters={"name": ["in", companies]},
				fields=["name", "default_currency"],
				limit_page_length=0,
			)
		}
		if companies
		else {}
	)
	values = _giving_values(donations, currency_by_company)
	current = frappe.db.get_value("Household", household, HOUSEHOLD_GIVING_FIELDS, as_dict=True) or {}
	if _rollup_changed(current, values):
		frappe.db.set_value("Household", household, values, update_modified=False)


def household_donor_names(household: str, *, for_update: bool = False) -> set[str]:
	household_person = frappe.qb.DocType("Household Person")
	contact_query = (
		frappe.qb.from_(household_person)
		.select(household_person.contact)
		.where(household_person.parenttype == "Household")
		.where(household_person.parent == household)
		.where(household_person.to_date.isnull() | (household_person.to_date == ""))
	)
	if for_update:
		contact_query = contact_query.for_update()
	contacts = contact_query.run(pluck=True)

	donor = frappe.qb.DocType("Donor")
	joint_subject = (donor.subject_household == household) & (
		(donor.subject_type == "Household") | donor.subject_type.isnull() | (donor.subject_type == "")
	)
	criteria = joint_subject
	if contacts:
		criteria = criteria | donor.contact.isin(sorted(set(contacts)))
	donor_query = frappe.qb.from_(donor).select(donor.name).where(criteria).orderby(donor.name)
	if for_update:
		donor_query = donor_query.for_update()
	return set(donor_query.run(pluck=True))


def recompute_households_for_donor(donor_name: str) -> None:
	if not donor_name or not frappe.db.exists("Donor", donor_name):
		return
	donor = (
		frappe.db.get_value(
			"Donor",
			donor_name,
			["subject_type", "subject_household", "contact"],
			as_dict=True,
		)
		or {}
	)
	households = set()
	if donor.subject_household and donor.subject_type in (None, "", "Household"):
		households.add(donor.subject_household)
	if donor.contact:
		from non_profit.non_profit.doctype.household.household import get_current_household

		if household := get_current_household(donor.contact):
			households.add(household)
	for household in sorted(households):
		recompute_household_giving(household)


def recompute_all_household_giving() -> int:
	count = 0
	last_name = ""
	while True:
		households = frappe.get_all(
			"Household",
			filters={"name": [">", last_name]} if last_name else None,
			pluck="name",
			order_by="name asc",
			limit_page_length=HOUSEHOLD_BATCH_SIZE,
		)
		if not households:
			break
		for household in households:
			recompute_household_giving(household)
		count += len(households)
		last_name = households[-1]
	return count


def _giving_values(donations, currency_by_company: dict[str, str | None]) -> dict:
	if not donations:
		return {
			"giving_currency": None,
			"giving_currency_conflict": 0,
			"total_lifetime_amount": 0.0,
			"gift_count": 0,
			"first_gift_date": None,
			"last_gift_date": None,
			"last_gift_amount": 0.0,
			"largest_gift_amount": 0.0,
		}

	resolved_currencies = [currency_by_company.get(row.company) for row in donations]
	currencies = {currency for currency in resolved_currencies if currency}
	single_currency = len(currencies) == 1 and all(resolved_currencies)
	latest = max(donations, key=lambda row: (getdate(row.date), row.modified, row.name))
	amounts = [flt(row.amount) for row in donations]
	return {
		"giving_currency": next(iter(currencies)) if single_currency else None,
		"giving_currency_conflict": 0 if single_currency else 1,
		"total_lifetime_amount": sum(amounts) if single_currency else None,
		"gift_count": len(donations),
		"first_gift_date": min(getdate(row.date) for row in donations),
		"last_gift_date": max(getdate(row.date) for row in donations),
		"last_gift_amount": flt(latest.amount) if single_currency else None,
		"largest_gift_amount": max(amounts) if single_currency else None,
	}


def _rollup_changed(current, desired: dict) -> bool:
	for fieldname, value in desired.items():
		current_value = current.get(fieldname)
		if fieldname in {"total_lifetime_amount", "last_gift_amount", "largest_gift_amount"}:
			if value is None:
				if current_value not in (None, ""):
					return True
				continue
			current_value = flt(current_value)
		elif fieldname == "giving_currency_conflict":
			current_value = int(current_value or 0)
		elif fieldname in {"first_gift_date", "last_gift_date"}:
			current_value = getdate(current_value) if current_value else None
		if current_value != value:
			return True
	return False
