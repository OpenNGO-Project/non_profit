import frappe
from frappe.utils import cstr, getdate

from non_profit.setup import setup_non_profit


def split_person_name(fullname: str | None) -> tuple[str, str]:
    parts = cstr(fullname).strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def get_company():
    company = frappe.defaults.get_defaults().company
    if company:
        return company
    else:
        company = frappe.get_list("Company", limit=1)
        if company:
            return company[0].name
    return None


def before_tests():
    # complete setup if missing
    from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

    use_short_test_host_name()

    if not frappe.get_list("Company"):
        setup_complete(
            {
                "currency": "USD",
                "full_name": "Test User",
                "company_name": "Frappe Care LLC",
                "timezone": "America/New_York",
                "company_abbr": "WP",
                "industry": "Healthcare",
                "country": "United States",
                "fy_start_date": "2021-01-01",
                "fy_end_date": "2021-12-31",
                "language": "english",
                "company_tagline": "Testing",
                "email": "test@erpnext.com",
                "password": "test",
                "chart_of_accounts": "Standard",
                "domains": ["Non Profit"],
            }
        )
        setup_non_profit()

    ensure_erpnext_bootstrap_customer_names()
    ensure_erpnext_bootstrap_addresses()
    ensure_test_fiscal_years()
    reset_item_prices()


def use_short_test_host_name():
    """Avoid oversized generated OAuth callback URLs during local full test runs."""

    if not frappe.flags.in_test:
        return
    frappe.local.conf.host_name = "http://development16.localhost"


def ensure_erpnext_bootstrap_customer_names():
    """Keep ERPNext's lazy test bootstrap compatible with local naming settings.

    ERPNext's test data later links Item Price rows to customers by fixed
    document name, for example `_Test Customer`. On Swiss/local benches the
    site can be configured to name Customer by naming series, leaving rows with
    the right `customer_name` but a numeric docname. Rename those test rows back
    to ERPNext's expected names before Frappe's legacy test-record preloader
    imports ERPNext test modules.
    """

    if not frappe.db.exists("DocType", "Customer"):
        return

    if (
        frappe.db.get_single_value("Selling Settings", "cust_master_name")
        != "Customer Name"
    ):
        frappe.db.set_single_value(
            "Selling Settings", "cust_master_name", "Customer Name"
        )
        frappe.clear_cache(doctype="Selling Settings")

    for customer_name in (
        "_Test Customer With Template",
        "_Test Customer P",
        "_Test Customer",
        "_Test Customer 1",
        "_Test Customer 2",
        "_Test Customer 3",
        "_Test Customer USD",
        "_Test Customer With Tax Category",
    ):
        if frappe.db.exists("Customer", customer_name):
            continue

        existing_name = frappe.db.get_value(
            "Customer", {"customer_name": customer_name}, "name"
        )
        if existing_name:
            frappe.rename_doc(
                "Customer",
                existing_name,
                customer_name,
                force=True,
                show_alert=False,
                rebuild_search=False,
            )
            continue

        if not (
            frappe.db.exists("Customer Group", "_Test Customer Group")
            and frappe.db.exists("Territory", "_Test Territory")
        ):
            continue

        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Individual",
                "customer_group": "_Test Customer Group",
                "territory": "_Test Territory",
            }
        ).insert(ignore_permissions=True)
        if customer.name != customer_name and not frappe.db.exists(
            "Customer", customer_name
        ):
            frappe.rename_doc(
                "Customer",
                customer.name,
                customer_name,
                force=True,
                show_alert=False,
                rebuild_search=False,
            )


def ensure_erpnext_bootstrap_addresses():
    """Pre-create ERPNext test addresses with locally mandatory fields.

    ERPNext's bootstrap records omit `pincode`. This bench makes that field
    mandatory, so the legacy bootstrap fails unless the address records already
    exist and are skipped by ERPNext's `make_records` helper.
    """

    if not frappe.db.exists("DocType", "Address"):
        return

    records = [
        (
            "_Test Billing Address Title",
            "Billing",
            "Address line 1",
            "_Test Customer 2",
        ),
        (
            "_Test Shipping Address 1 Title",
            "Shipping",
            "Address line 2",
            "_Test Customer 2",
        ),
        (
            "_Test Shipping Address 2 Title",
            "Shipping",
            "Address line 3",
            "_Test Customer 2",
        ),
        (
            "_Test Billing Address 2 Title",
            "Billing",
            "Address line 4",
            "_Test Customer 1",
        ),
    ]
    for title, address_type, line1, customer in records:
        if frappe.db.exists(
            "Address", {"address_title": title, "address_type": address_type}
        ):
            continue
        if not frappe.db.exists("Customer", customer):
            continue

        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_type": address_type,
                "address_line1": line1,
                "address_title": title,
                "city": "Lagos",
                "pincode": "100001",
                "country": "Nigeria",
                "links": [
                    {
                        "link_doctype": "Customer",
                        "link_name": customer,
                        "doctype": "Dynamic Link",
                    }
                ],
            }
        )
        if title in {"_Test Shipping Address 2 Title", "_Test Billing Address 2 Title"}:
            address.is_shipping_address = "1"
        address.insert(ignore_permissions=True)


def ensure_test_fiscal_years():
    default_company = get_company()

    if default_company and frappe.db.exists("Fiscal Year", "2021"):
        fy_2021 = frappe.get_doc("Fiscal Year", "2021")
        if not fy_2021.companies:
            fy_2021.append("companies", {"company": default_company})
            fy_2021.save(ignore_permissions=True)

    today = getdate()
    global_fy_exists = False

    for fy in frappe.get_all(
        "Fiscal Year",
        filters={"disabled": 0},
        fields=["name", "year_start_date", "year_end_date"],
    ):
        if fy.year_start_date <= today <= fy.year_end_date and not frappe.db.exists(
            "Fiscal Year Company", {"parent": fy.name}
        ):
            global_fy_exists = True
            break

    if not global_fy_exists:
        frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": f"{today.year}-Global",
                "year_start_date": f"{today.year}-01-01",
                "year_end_date": f"{today.year}-12-31",
            }
        ).insert(ignore_permissions=True)


def reset_item_prices():
    frappe.db.delete("Item Price")
