from frappe import _


def get_data():
	return {
		"fieldname": "donor_interaction",
		"transactions": [
			{"label": _("Follow-up"), "items": ["Task"]},
		],
	}
