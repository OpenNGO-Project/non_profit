"""
Create contacts for customers.

Run: bench --site <site> execute non_profit.fixtures.create_contacts.create_contacts_for_customers
"""

import frappe
import re


def create_contacts_for_customers():
    """Create contacts for all customers that don't have one."""
    first_names = [
        "John",
        "Jane",
        "Michael",
        "Sarah",
        "David",
        "Emily",
        "Robert",
        "Lisa",
        "William",
        "Jennifer",
        "James",
        "Amanda",
        "Thomas",
        "Jessica",
        "Daniel",
        "Ashley",
        "Matthew",
        "Nicole",
        "Anthony",
        "Stephanie",
        "Mark",
        "Elizabeth",
        "Steven",
        "Rebecca",
        "Paul",
        "Rachel",
        "Andrew",
        "Samantha",
        "Joshua",
        "Megan",
    ]

    last_names = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Garcia",
        "Miller",
        "Davis",
        "Rodriguez",
        "Martinez",
        "Hernandez",
        "Lopez",
        "Gonzalez",
        "Wilson",
        "Anderson",
        "Thomas",
        "Taylor",
        "Moore",
        "Jackson",
        "Martin",
        "Lee",
        "Perez",
        "Thompson",
        "White",
        "Harris",
        "Sanchez",
        "Clark",
        "Ramirez",
        "Lewis",
        "Robinson",
    ]

    def create_slug(name):
        name = name.lower()
        name = re.sub(r"[^a-z0-9]", "", name)
        return name[:15]

    customers = frappe.db.sql(
        """
		SELECT c.name, c.customer_name
		FROM `tabCustomer` c
		WHERE NOT EXISTS (
			SELECT 1 FROM `tabDynamic Link` dl
			INNER JOIN `tabContact` contact ON contact.name = dl.parent
			WHERE dl.link_doctype = 'Customer'
			AND dl.link_name = c.name
			AND dl.parenttype = 'Contact'
		)
	""",
        as_dict=True,
    )

    print(f"Found {len(customers)} customers without contacts")

    created = 0
    for i, customer in enumerate(customers):
        try:
            first_name = first_names[i % len(first_names)]
            last_name = last_names[(i + 7) % len(last_names)]

            contact = frappe.new_doc("Contact")
            contact.first_name = first_name
            contact.last_name = last_name
            contact.is_primary_contact = 1

            email_slug = create_slug(customer.customer_name)
            email = f"{email_slug}{i}@example.com"
            contact.add_email(email, is_primary=1)

            contact.insert(ignore_permissions=True)

            contact.append(
                "links", {"link_doctype": "Customer", "link_name": customer.name}
            )
            contact.save(ignore_permissions=True)

            created += 1
        except Exception as e:
            print(f"Error for {customer.name}: {str(e)[:60]}")

    frappe.db.commit()
    print(f"Done! Created {created} contacts")
    return created


def link_members_to_contacts():
    """Link all Members to their Customer's Contact."""
    members = frappe.get_all("Member", fields=["name", "customer"])
    updated = 0
    for member in members:
        contact = frappe.db.sql(
            """
			SELECT c.name
			FROM `tabContact` c
			INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name
			WHERE dl.link_doctype = 'Customer'
			AND dl.link_name = %s
			AND dl.parenttype = 'Contact'
			LIMIT 1
		""",
            member.customer,
            as_dict=True,
        )
        if contact:
            frappe.db.set_value("Member", member.name, "contact", contact[0].name)
            updated += 1

    frappe.db.commit()
    print(f"Updated {updated} members with contact links")
    return updated
