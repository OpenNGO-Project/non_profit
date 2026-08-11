app_name = "non_profit"
app_title = "Non Profit"
app_publisher = "Frappe"
app_description = "Non Profit"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "pandikunta@frappe.io"
app_license = "GNU General Public License (v3)"

required_apps = ["erpnext"]

demo_data_reset_declarations = [
	"non_profit.non_profit.demo_data_reset.get_reset_declaration",
]

jinja = {
	"methods": [
		"non_profit.non_profit.swiss_qrbill.swiss_qrbill_svg",
	]
}

doctype_js = {
	"Donor": "public/js/npo_next_actions.js",
	"Major Gift": "public/js/npo_next_actions.js",
}

# Neutral multi-channel campaign launcher dialog (window.npoChannelLaunch),
# used by NPO Recipient Selection and optional source forms.
app_include_js = ["/assets/non_profit/js/channel_launch.js"]

before_install = "non_profit.setup.before_install"
after_install = "non_profit.setup.setup_non_profit"
after_app_install = "non_profit.setup.after_app_install"
before_migrate = "non_profit.setup.before_migrate"
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
		"validate": "non_profit.non_profit.next_actions.validate_task_links",
		"on_update": "non_profit.non_profit.next_actions.on_task_change",
		"on_trash": [
			"non_profit.non_profit.next_actions.validate_task_parent_permissions",
			"non_profit.non_profit.next_actions.on_task_change",
		],
	},
}

good_connector_ebics_reconciliation_providers = [
	"non_profit.non_profit.bank_integration.get_ebics_reconciliation_candidates",
]

good_newsletter_audience_providers = [
	"non_profit.non_profit.recipient_selection.newsletter_audience_provider",
]

# Optional postal letter production for Spendenbescheinigungen. The hook is
# inert when no downstream campaign app consumes it.
good_direct_mail_audience_providers = [
	"non_profit.non_profit.tax_receipts.direct_mail_audience_provider",
]

# Neutral multi-channel launch seam. Channel apps register factories returning
# {"key", "label", "launch_fields", "create_campaign"}; non_profit never imports
# the private channel apps itself.
non_profit_audience_channel_creators = []
non_profit_audience_source_providers = []

# Neutral seam for payment providers that own a recurring schedule. Registered
# providers are called as provider(action="change_amount"|"cancel"|
# "verify_abandoned_pending_mandate", schedule=<Recurring Donation>, **kwargs).
# Mutations return True once handled; recovery returns provider evidence with
# safe_to_retire=True only after proving that no payment or mandate can exist.
# non_profit is public and never imports a payment integration itself.
non_profit_recurring_donation_providers = []

# Neutral seam for the public /donate page. A payment integration registers a
# provider that creates the Donation (and schedule, for a recurring gift) and
# returns a checkout URL. The provider also receives the per-render request_key
# so it can replay a recurring reservation idempotently. Without one, /donate
# records the gift and collects nothing, which is the historical behaviour.
non_profit_public_donation_checkout_providers = []

scheduler_events = {
	"daily": [
		"non_profit.non_profit.doctype.membership.membership.set_expired_status",
		"non_profit.non_profit.doctype.recurring_donation.recurring_donation.process_recurring_donations",
		"non_profit.non_profit.major_gifts.reconcile_fundraising_rollups",
		"non_profit.non_profit.recurring_reconciliation.reconcile_recurring_donations",
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
		{"doctype": "NPO Recipient Selection", "index": 13},
	]
}
