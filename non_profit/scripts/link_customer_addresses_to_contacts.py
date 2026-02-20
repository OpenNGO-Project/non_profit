"""Link Customer addresses to their Contacts.

Run with:
    bench --site [site] execute non_profit.scripts.link_customer_addresses_to_contacts.link_addresses_to_contacts
"""

import frappe


def link_addresses_to_contacts():
    """Link addresses from Customer to Contacts that don't have addresses."""
    # Find all Contacts linked to Customers
    contact_customer_links = frappe.db.sql(
        """
        SELECT dl.parent as contact, dl.link_name as customer
        FROM `tabDynamic Link` dl
        WHERE dl.link_doctype = 'Customer'
        AND dl.parenttype = 'Contact'
    """,
        as_dict=True,
    )

    updated = 0
    already_has_address = 0
    no_customer_address = 0

    for row in contact_customer_links:
        contact_name = row.contact
        customer_name = row.customer

        # Check if contact already has an address
        existing_address = frappe.db.exists(
            "Dynamic Link",
            {
                "parenttype": "Address",
                "link_doctype": "Contact",
                "link_name": contact_name,
            },
        )

        if existing_address:
            already_has_address += 1
            continue

        # Find addresses linked to the Customer
        customer_addresses = frappe.db.sql(
            """
            SELECT dl.parent as address_name, a.is_primary_address
            FROM `tabDynamic Link` dl
            INNER JOIN `tabAddress` a ON a.name = dl.parent
            WHERE dl.link_doctype = 'Customer'
            AND dl.link_name = %s
            AND dl.parenttype = 'Address'
            ORDER BY a.is_primary_address DESC
        """,
            customer_name,
            as_dict=True,
        )

        if not customer_addresses:
            no_customer_address += 1
            continue

        # Link the primary (or first) address to the Contact
        address_to_link = customer_addresses[0].address_name

        # Add the Contact link to the existing address
        address_doc = frappe.get_doc("Address", address_to_link)

        # Check if this contact is already linked
        already_linked = any(
            link.link_doctype == "Contact" and link.link_name == contact_name
            for link in address_doc.links
        )

        if not already_linked:
            address_doc.append(
                "links",
                {"link_doctype": "Contact", "link_name": contact_name},
            )
            address_doc.save(ignore_permissions=True)
            updated += 1
            print(f"Linked {address_to_link} to Contact {contact_name}")

    frappe.db.commit()

    print(f"\nSummary:")
    print(f"  Updated: {updated}")
    print(f"  Already had address: {already_has_address}")
    print(f"  No customer address: {no_customer_address}")
    print(f"  Total contacts checked: {len(contact_customer_links)}")

    return {
        "updated": updated,
        "already_has_address": already_has_address,
        "no_customer_address": no_customer_address,
        "total": len(contact_customer_links),
    }
