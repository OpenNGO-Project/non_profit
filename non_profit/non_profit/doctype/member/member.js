// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Member', {
	refresh: function(frm) {

		frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Member'};

		frm.toggle_display(['address_html','contact_html'], !frm.doc.__islocal);

		if(!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			// custom buttons
			frm.page.add_action_item(__('Accounting Ledger'), function() {
				if (frm.doc.customer) {
					frappe.set_route('query-report', 'General Ledger', {party_type: 'Customer', party: frm.doc.customer});
				} else {
					frappe.set_route('query-report', 'General Ledger', {party_type: 'Member', party: frm.doc.name});
				}
			});

			frm.page.add_action_item(__('Accounts Receivable'), function() {
				frappe.set_route('query-report', 'Accounts Receivable', {customer: frm.doc.customer});
			});

			if (!frm.doc.customer) {
				frm.page.add_action_item(__('Create Customer'), () => {
					frm.call('make_customer_and_link').then(() => {
						frm.reload_doc();
					});
				});
			}

			frm.page.add_action_item(__('Create Membership'), () => {
				frm.call('create_membership').then((r) => {
					if (r.message) {
						frappe.set_route('Form', 'Membership', r.message);
					}
				});
			});

			// indicator
			erpnext.utils.set_party_dashboard_indicators(frm);

		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}

		frappe.call({
			method:"frappe.client.get_value",
			args:{
				'doctype':"Membership",
				'filters':{'member': frm.doc.name},
				'fieldname':[
					'to_date'
				]
			},
			callback: function (data) {
				if(data.message) {
					frappe.model.set_value(frm.doctype,frm.docname,
						"membership_expiry_date", data.message.to_date);
				}
			}
		});
	}
});
