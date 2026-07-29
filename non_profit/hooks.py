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
after_app_install = "non_profit.setup.after_app_install"
after_migrate = "non_profit.setup.after_migrate"
before_uninstall = "non_profit.setup.before_uninstall"

override_doctype_class = {
	"Bank Transaction": "non_profit.non_profit.custom_doctype.bank_transaction.NonProfitBankTransaction",
}

doc_events = {
	"Contact": {
		"validate": "non_profit.non_profit.utils.validate_contact_identity_kind",
	},
	"Membership": {
		"validate": "non_profit.non_profit.membership_sync.validate_no_overlap",
	},
	"Donation": {
		"on_submit": [
			"non_profit.non_profit.major_gifts.on_donation_change",
			"non_profit.non_profit.bank_integration.register_donation_qr_reference",
		],
		"on_cancel": "non_profit.non_profit.major_gifts.on_donation_change",
		"on_trash": "non_profit.non_profit.major_gifts.on_donation_change",
	},
	"Payment Entry": {
		# The Donation delta deliberately lives in doc_events, not in
		# override_doctype_class: the override resolves to the last installed
		# app (hrms wins on this bench), while doc_events fire for every
		# Payment Entry regardless of which controller class is active.
		"before_validate": "non_profit.non_profit.custom_doctype.payment_entry.validate_donation_payment_entry_companies",
		"validate": "non_profit.non_profit.custom_doctype.payment_entry.validate_donation_payment_entry_references",
		"on_submit": "non_profit.non_profit.custom_doctype.payment_entry.sync_donation_accounting_state_for_payment_entry",
		"on_cancel": "non_profit.non_profit.custom_doctype.payment_entry.sync_donation_accounting_state_for_payment_entry",
		"on_change": "non_profit.non_profit.custom_doctype.payment_entry.sync_donation_reconciliation_state_on_payment_entry_change",
	},
	"Task": {
		"on_update": "non_profit.non_profit.next_actions.on_task_change",
		"on_trash": "non_profit.non_profit.next_actions.on_task_change",
	},
}

good_connector_ebics_reconciliation_providers = [
	"non_profit.non_profit.bank_integration.get_ebics_reconciliation_candidates",
]

scheduler_events = {
	"daily": [
		"non_profit.non_profit.doctype.membership.membership.set_expired_status",
		"non_profit.non_profit.doctype.recurring_donation.recurring_donation.process_recurring_donations",
		"non_profit.non_profit.major_gifts.reconcile_fundraising_rollups",
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
		{"doctype": "Major Gift", "index": 12},
	]
}
