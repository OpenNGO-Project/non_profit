// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Non Profit Settings", {
	refresh: function(frm) {
		frm.set_query("inv_print_format", function() {
			return {
				filters: {
					"doc_type": "Sales Invoice"
				}
			};
		});

		frm.set_query("membership_print_format", function() {
			return {
				filters: {
					"doc_type": "Membership"
				}
			};
		});

		frm.set_query("membership_debit_account", function() {
			return {
				filters: {
					"account_type": "Receivable",
					"is_group": 0,
					"company": frm.doc.company
				}
			};
		});

		frm.set_query("donation_debit_account", function() {
			return {
				filters: {
					"account_type": "Receivable",
					"is_group": 0,
					"company": frm.doc.donation_company
				}
			};
		});

		frm.set_query("membership_payment_account", function () {
			var account_types = ["Bank", "Cash"];
			return {
				filters: {
					"account_type": ["in", account_types],
					"is_group": 0,
					"company": frm.doc.company
				}
			};
		});

		frm.set_query("donation_payment_account", function () {
			var account_types = ["Bank", "Cash"];
			return {
				filters: {
					"account_type": ["in", account_types],
					"is_group": 0,
					"company": frm.doc.donation_company
				}
			};
		});

		let docs_url = "https://docs.erpnext.com/docs/user/manual/en/non_profit/membership";

		frm.set_intro(__("You can learn more about memberships in the manual. ") + `<a href='${docs_url}'>${__('ERPNext Docs')}</a>`, true);
	}
});
