import frappe

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


def get_default_company():
    """Get default company from Non Profit Settings or first company."""
    company = frappe.db.get_single_value("Non Profit Settings", "company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        if companies:
            company = companies[0].name
    return company


def get_customer_group():
    """Get or create customer group for members."""
    group = frappe.db.exists("Customer Group", "Members")
    if group:
        return group

    root = frappe.db.get_value("Customer Group", {"is_group": 1}, "name")

    customer_group = frappe.new_doc("Customer Group")
    customer_group.update(
        {
            "customer_group_name": "Members",
            "parent_customer_group": root or "All Customer Groups",
        }
    )
    customer_group.insert()

    return customer_group.name


def get_territory():
    """Get default territory."""
    territory = frappe.db.get_value("Territory", {"is_group": 1}, "name")
    return territory or "All Territories"


def get_default_membership_type():
    """Get or create default membership type."""
    membership_type = frappe.db.exists("Membership Type", "Standard Membership")
    if membership_type:
        return membership_type

    types = frappe.get_all("Membership Type", limit=1)
    if types:
        return types[0].name

    return None


def get_or_create_membership_type():
    """Get or create a standard membership type with item."""
    membership_type = frappe.db.exists("Membership Type", "Standard Membership")
    if membership_type:
        return membership_type

    item = get_or_create_membership_item()

    doc = frappe.new_doc("Membership Type")
    doc.membership_type = "Standard Membership"
    doc.amount = 60
    doc.linked_item = item.name
    doc.auto_create_subscription_plan = 1
    doc.insert()
    frappe.db.commit()
    return doc.name


def get_or_create_membership_item():
    """Get or create membership item."""
    item_code = "Membership"
    existing = frappe.db.exists("Item", item_code)
    if existing:
        return frappe.get_doc("Item", existing)

    item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
    if not item_group:
        item_group = "Products"

    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = "Membership"
    item.item_group = item_group
    item.stock_uom = "nos"
    item.is_stock_item = 0
    item.is_sales_item = 1
    item.insert()
    frappe.db.commit()
    return item


def before_tests():
    from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

    if not frappe.get_list("Company"):
        setup_complete(
            {
                "currency": "USD",
                "full_name": "Test User",
                "company_name": "Test Company",
                "timezone": "America/New_York",
                "company_abbr": "TC",
                "industry": "Services",
                "country": "United States",
                "fy_start_date": "2021-01-01",
                "fy_end_date": "2021-12-31",
                "language": "english",
                "company_tagline": "Testing",
                "email": "test@example.com",
                "password": "test",
                "chart_of_accounts": "Standard",
                "domains": ["Non Profit"],
            }
        )
        setup_non_profit()
