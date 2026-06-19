from frappe import _


def get_data():
	return {
		"fieldname": "major_gift",
		"transactions": [
			{"label": _("Cultivation"), "items": ["Donor Interaction", "Task"]},
			{"label": _("Giving"), "items": ["Donation"]},
		],
	}
