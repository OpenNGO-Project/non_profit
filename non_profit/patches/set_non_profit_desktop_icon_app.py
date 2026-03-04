import frappe


def execute():
    frappe.db.set_value(
        "Workspace", "Non Profit", "app", "non_profit", update_modified=False
    )
    frappe.db.set_value(
        "Desktop Icon", "Non Profit", "app", "non_profit", update_modified=False
    )
