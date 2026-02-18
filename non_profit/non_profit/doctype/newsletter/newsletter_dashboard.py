from frappe import _


def get_data():
    return {
        "fieldname": "name",
        "non_standard_fieldnames": {"Email Queue": "reference_name"},
        "transactions": [
            {
                "label": _("Email Group"),
                "items": ["Email Group"],
            },
        ],
        "reports": [],
    }
