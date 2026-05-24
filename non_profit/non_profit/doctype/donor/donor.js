// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Donor', {
	refresh: function(frm) {
		frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Donor'};

		frm.toggle_display(['address_html','contact_html'], !frm.doc.__islocal);

		if(!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			frm.page.add_action_item(__('Accounting Ledger'), function() {
				if (frm.doc.customer) {
					frappe.set_route('query-report', 'General Ledger', {party_type: 'Customer', party: frm.doc.customer});
				} else {
					frappe.set_route('query-report', 'General Ledger', {party_type: 'Donor', party: frm.doc.name});
				}
			});

			if (frm.doc.customer) {
				frm.page.add_action_item(__('Accounts Receivable'), function() {
					frappe.set_route('query-report', 'Accounts Receivable', {customer: frm.doc.customer});
				});
			} else {
				frm.page.add_action_item(__('Create Customer'), () => {
					frm.call('make_customer_and_link').then(() => {
						frm.reload_doc();
					});
				});
			}

			erpnext.utils.set_party_dashboard_indicators(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}

	}
});
