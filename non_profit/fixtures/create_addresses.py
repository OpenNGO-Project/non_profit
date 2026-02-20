"""Populate addresses for all customers with sample German addresses."""

import frappe
import random


def execute():
    """Create addresses for all customers that don't have one."""
    cities = [
        ("10115", "Berlin", "Mitte"),
        ("80331", "München", "Altstadt"),
        ("50667", "Köln", "Innenstadt"),
        ("60311", "Frankfurt", "Altstadt"),
        ("70173", "Stuttgart", "Mitte"),
        ("20095", "Hamburg", "Altstadt"),
        ("30159", "Hannover", "Mitte"),
        ("40210", "Düsseldorf", "Stadtmitte"),
        ("80339", "München", "Westend"),
        ("81667", "München", "Haidhausen"),
        ("85354", "Freising", "Stadt"),
        ("82205", "Gilching", "Stadt"),
        ("82319", "Starnberg", "Stadt"),
        ("82131", "Gauting", "Stadt"),
        ("82049", "Pullach", "Stadt"),
        ("82234", "Wessling", "Stadt"),
        ("80939", "München", "Schwabing"),
        ("80686", "München", "Sendling"),
        ("82008", "Unterhaching", "Stadt"),
        ("85579", "Neubiberg", "Stadt"),
        ("80335", "München", "Maxvorstadt"),
        ("80469", "München", "Glockenbach"),
        ("80796", "München", "Schwabing-West"),
        ("81541", "München", "Giesing"),
        ("81373", "München", "Sendling-Westpark"),
    ]

    streets = [
        "Hauptstraße",
        "Bahnhofstraße",
        "Schulstraße",
        "Kirchstraße",
        "Gartenstraße",
        "Lindenstraße",
        "Bachstraße",
        "Parkstraße",
        "Mühlstraße",
        "Marktstraße",
        "Rathausstraße",
        "Dorfstraße",
        "Waldstraße",
        "Bergstraße",
        "Brunnenstraße",
        "Friedhofstraße",
        "Mühldorfer Straße",
        "Münchner Straße",
        "Weißenseestraße",
        "Wolfratshauser Straße",
        "Isartalstraße",
        "Sauerbruchstraße",
        "Herzogstraße",
        "Prinzregentenstraße",
        "Leopoldstraße",
        "Sendlinger Straße",
        "Tal",
    ]

    customers = frappe.get_all("Customer", fields=["name", "customer_name"])
    print(f"Creating addresses for {len(customers)} customers...")

    created = 0
    for idx, customer in enumerate(customers):
        existing = frappe.db.exists(
            "Dynamic Link",
            {
                "link_doctype": "Customer",
                "link_name": customer.name,
                "parenttype": "Address",
            },
        )
        if existing:
            continue

        city_data = cities[idx % len(cities)]
        street = streets[idx % len(streets)]
        house_num = random.randint(1, 150)

        address = frappe.new_doc("Address")
        address.address_title = customer.customer_name
        address.address_type = "Billing"
        address.address_line1 = f"{street} {house_num}"
        address.pincode = city_data[0]
        address.city = city_data[1]
        address.country = "Germany"
        address.insert(ignore_permissions=True)

        address.append(
            "links",
            {
                "link_doctype": "Customer",
                "link_name": customer.name,
            },
        )
        address.save(ignore_permissions=True)
        created += 1
        print(
            f"  [{created}] {customer.customer_name}: {street} {house_num}, {city_data[0]} {city_data[1]}"
        )

    frappe.db.commit()
    print(f"\nCreated {created} addresses")
