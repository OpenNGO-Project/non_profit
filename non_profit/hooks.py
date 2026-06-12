app_name = "non_profit"
app_title = "Non Profit"
app_publisher = "Frappe"
app_description = "Non Profit"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "pandikunta@frappe.io"
app_license = "MIT"

required_apps = ["erpnext"]

jinja = {
	"methods": [
		"non_profit.non_profit.swiss_qrbill.swiss_qrbill_svg",
	]
}

after_install = "non_profit.setup.setup_non_profit"
after_migrate = "non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures"

override_doctype_class = {
	"Bank Transaction": "non_profit.non_profit.custom_doctype.bank_transaction.NonProfitBankTransaction",
	"Payment Entry": "non_profit.non_profit.custom_doctype.payment_entry.NonProfitPaymentEntry",
}

doc_events = {
	"Membership": {
		"validate": "non_profit.non_profit.membership_sync.validate_no_overlap",
	},
}

scheduler_events = {
	"daily": [
		"non_profit.non_profit.doctype.membership.membership.set_expired_status",
		"non_profit.non_profit.doctype.recurring_donation.recurring_donation.process_recurring_donations",
	],
}

before_tests = "non_profit.non_profit.utils.before_tests"

global_search_doctypes = {
	"Non Profit": [
		{"doctype": "Volunteer", "index": 3},
		{"doctype": "Membership", "index": 4},
		{"doctype": "Member", "index": 5},
		{"doctype": "Donor", "index": 6},
		{"doctype": "Chapter", "index": 7},
		{"doctype": "Grant Application", "index": 8},
		{"doctype": "Volunteer Type", "index": 9},
		{"doctype": "Donor Type", "index": 10},
		{"doctype": "Membership Type", "index": 11},
	]
}
