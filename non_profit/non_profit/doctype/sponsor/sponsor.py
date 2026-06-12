import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

from non_profit.non_profit.doctype.donor.donor import (
	_check_identity_doc_permission,
	get_or_create_donor_for_contact,
	get_or_create_donor_for_customer,
)


class Sponsor(Document):
	def validate(self):
		if self.contract_end and self.contract_start and self.contract_end < self.contract_start:
			frappe.throw("Contract End cannot be before Contract Start")


@frappe.whitelist(methods=["POST"])
def create_sponsor_from_identity(
	contact: str | None = None,
	customer: str | None = None,
	donor_type: str | None = None,
	tier: str | None = None,
) -> dict[str, str | None]:
	contact = cstr(contact).strip()
	customer = cstr(customer).strip()
	tier = cstr(tier).strip()
	if not contact and not customer:
		frappe.throw(_("Select a Contact or a Customer."))
	frappe.has_permission("Sponsor", "create", throw=True)
	frappe.has_permission("Donor", "create", throw=True)
	if contact:
		_check_identity_doc_permission("Contact", contact, "write")
	if customer:
		_check_identity_doc_permission("Customer", customer, "write")

	if contact:
		donor = get_or_create_donor_for_contact(contact, customer=customer or None, donor_type=donor_type)
	else:
		donor = get_or_create_donor_for_customer(customer, donor_type=donor_type)

	sponsor_name = frappe.db.exists("Sponsor", {"donor": donor.name})
	if sponsor_name:
		sponsor = frappe.get_doc("Sponsor", sponsor_name)
		sponsor.check_permission("write" if tier and sponsor.get("tier") != tier else "read")
		if tier and sponsor.get("tier") != tier:
			sponsor.tier = tier
			sponsor.save()
	else:
		sponsor = frappe.new_doc("Sponsor")
		sponsor.donor = donor.name
		if tier:
			sponsor.tier = tier
		sponsor.insert()

	return {
		"sponsor": sponsor.name,
		"donor": donor.name,
		"customer": donor.get("customer"),
		"contact": contact or None,
	}
