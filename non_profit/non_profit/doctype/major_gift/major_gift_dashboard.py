from frappe import _


def get_data():
	return {
		"fieldname": "major_gift",
		"transactions": [
			{"label": _("Follow-up"), "items": ["Task"]},
			{"label": _("Giving"), "items": ["Donation"]},
		],
	}
