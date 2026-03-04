import frappe
from frappe.utils import getdate

from non_profit.setup import setup_non_profit


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

    ensure_test_fiscal_years()
    reset_item_prices()


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
