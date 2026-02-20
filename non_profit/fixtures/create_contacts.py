import frappe
import re


def create_contacts_for_customers():
    first_names = [
        "Hans",
        "Peter",
        "Klaus",
        "Wolfgang",
        "Dieter",
        "Gerhard",
        "Heinz",
        "Werner",
        "Manfred",
        "Helmut",
        "Maria",
        "Anna",
        "Elisabeth",
        "Margarete",
        "Gertrud",
        "Helga",
        "Ursula",
        "Ingrid",
        "Monika",
        "Erika",
        "Thomas",
        "Michael",
        "Andreas",
        "Stefan",
        "Markus",
        "Christian",
        "Martin",
        "Frank",
        "Uwe",
        "Juergen",
        "Julia",
        "Laura",
        "Lisa",
        "Sarah",
        "Sophie",
        "Leonie",
        "Lena",
        "Hannah",
        "Emma",
        "Lina",
    ]

    last_names = [
        "Mueller",
        "Schmidt",
        "Schneider",
        "Fischer",
        "Weber",
        "Meyer",
        "Wagner",
        "Becker",
        "Schulz",
        "Hoffmann",
        "Schaefer",
        "Koch",
        "Bauer",
        "Richter",
        "Klein",
        "Wolf",
        "Schroeder",
        "Neumann",
        "Schwarz",
        "Braun",
        "Zimmermann",
        "Krueger",
        "Hofmann",
        "Hartmann",
        "Lange",
        "Schmitt",
        "Werner",
        "Krause",
        "Meier",
        "Lehmann",
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
            email = f"{email_slug}{i}@test-oedp.de"
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


def create_addresses_for_customers():
    """Create addresses for customers that don't have them."""
    street_names = [
        "Hauptstrasse",
        "Bahnhofstrasse",
        "Schulstrasse",
        "Kirchstrasse",
        "Marktstrasse",
        "Lindenstrasse",
        "Bergstrasse",
        "Gartenstrasse",
        "Birkenweg",
        "Ahornweg",
        "Mozartstrasse",
        "Goethestrasse",
        "Schillerstrasse",
        "Kantstrasse",
        "Rathausstrasse",
        "Parkstrasse",
        "Waldstrasse",
        "Seestrasse",
        "Bergweg",
        "Talstrasse",
    ]

    cities = [
        ("Berlin", "10115"),
        ("Muenchen", "80331"),
        ("Hamburg", "20095"),
        ("Frankfurt", "60311"),
        ("Koeln", "50667"),
        ("Stuttgart", "70173"),
        ("Duesseldorf", "40213"),
        ("Dortmund", "44137"),
        ("Essen", "45127"),
        ("Leipzig", "04109"),
        ("Bremen", "28195"),
        ("Dresden", "01067"),
        ("Hannover", "30159"),
        ("Nuernberg", "90402"),
        ("Duisburg", "47051"),
    ]

    customers = frappe.db.sql(
        """
        SELECT c.name, c.customer_name
        FROM `tabCustomer` c
        WHERE NOT EXISTS (
            SELECT 1 FROM `tabDynamic Link` dl
            INNER JOIN `tabAddress` addr ON addr.name = dl.parent
            WHERE dl.link_doctype = 'Customer'
            AND dl.link_name = c.name
            AND dl.parenttype = 'Address'
        )
    """,
        as_dict=True,
    )

    print(f"Found {len(customers)} customers without addresses")

    created = 0
    for i, customer in enumerate(customers):
        try:
            street = street_names[i % len(street_names)]
            city, pincode = cities[i % len(cities)]
            street_number = (i * 7) % 100 + 1

            address = frappe.new_doc("Address")
            address.address_title = customer.customer_name[:40]
            address.address_type = "Billing"
            address.address_line1 = f"{street} {street_number}"
            address.city = city
            address.pincode = pincode
            address.country = "Germany"

            address.insert(ignore_permissions=True)

            address.append(
                "links", {"link_doctype": "Customer", "link_name": customer.name}
            )
            address.save(ignore_permissions=True)

            created += 1
        except Exception as e:
            print(f"Error for {customer.name}: {str(e)[:60]}")

    frappe.db.commit()
    print(f"Done! Created {created} addresses")
    return created
