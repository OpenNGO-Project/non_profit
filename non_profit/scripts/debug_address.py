import frappe
from non_profit.non_profit.doctype.letter_campaign.letter_campaign import (
    get_contact_from_member,
    get_primary_address,
)

member_name = frappe.db.get_value("Member", {}, "name")
print(f"Testing member: {member_name}")

if member_name:
    contact_name = get_contact_from_member(member_name)
    print(f"Contact found: {contact_name}")

    if contact_name:
        customer = frappe.db.get_value("Member", member_name, "customer")
        print(f"Customer: {customer}")

        contact = frappe.get_doc("Contact", contact_name)
        print(f"Contact name: {contact.name}")

        address = get_primary_address(contact, member_name)
        print(f"Address found: {address}")
    else:
        print("No contact linked to member")
