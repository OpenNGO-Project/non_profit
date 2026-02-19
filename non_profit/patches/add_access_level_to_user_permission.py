"""
Add access_level custom field to User Permission DocType.

This patch adds a custom Select field to the User Permission DocType
to support per-chapter access levels (Full Access, Finance, Read Only).

Run: bench --site <site> execute non_profit.patches.add_access_level_to_user_permission.execute
"""

import frappe


def execute():
    """Add access_level field to User Permission DocType."""

    field_name = "access_level"

    if frappe.db.exists(
        "Custom Field", {"dt": "User Permission", "fieldname": field_name}
    ):
        print(f"Custom field '{field_name}' already exists on User Permission")
        return

    custom_field = frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": "User Permission",
            "label": "Access Level",
            "fieldname": field_name,
            "fieldtype": "Select",
            "options": "Full Access\nFinance\nRead Only",
            "default": "Read Only",
            "insert_after": "for_value",
            "permlevel": 0,
            "in_list_view": 1,
            "in_standard_filter": 1,
        }
    )
    custom_field.insert()

    frappe.db.commit()
    print(f"Added custom field '{field_name}' to User Permission DocType")
