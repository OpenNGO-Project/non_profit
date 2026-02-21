"""
Populate addresses for all customers with sample addresses.

Run: bench --site <site> execute non_profit.fixtures.create_addresses.execute
"""

import frappe
import random


def execute():
    """Create addresses for all customers that don't have one."""
    cities = [
        ("10001", "City A"),
        ("20002", "City B"),
        ("30003", "City C"),
        ("40004", "City D"),
        ("50005", "City E"),
        ("60006", "City F"),
        ("70007", "City G"),
        ("80008", "City H"),
    ]

    streets = [
        "Main Street",
        "Park Avenue",
        "Oak Street",
        "Maple Drive",
        "Cedar Lane",
        "Pine Road",
        "Elm Street",
        "Washington Street",
    ]

    countries = ["United States", "Canada", "United Kingdom", "Germany", "Australia"]

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
        country = countries[idx % len(countries)]

        address = frappe.new_doc("Address")
        address.address_title = customer.customer_name
        address.address_type = "Billing"
        address.address_line1 = f"{street} {house_num}"
        address.city = city_data[1]
        address.pincode = city_data[0]
        address.country = country
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
