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
			show_donor_creation_dialog(frm);
		}

	}
});

function show_donor_creation_dialog(frm) {
	if (frm.__donor_creation_dialog_shown) return;
	frm.__donor_creation_dialog_shown = true;

	const dialog = new frappe.ui.Dialog({
		title: __('Create Donor'),
		fields: [
			{
				fieldname: 'contact',
				fieldtype: 'Link',
				label: __('Contact'),
				options: 'Contact',
			},
			{
				fieldname: 'customer',
				fieldtype: 'Link',
				label: __('Customer'),
				options: 'Customer',
			},
			{
				fieldname: 'donor_type',
				fieldtype: 'Link',
				label: __('Donor Type'),
				options: 'Donor Type',
			},
		],
		primary_action_label: __('Create'),
		primary_action(values) {
			if (!values.contact && !values.customer) {
				frappe.msgprint(__('Select a Contact or a Customer.'));
				return;
			}

			frappe.call({
				method: 'non_profit.non_profit.doctype.donor.donor.create_donor_from_identity',
				args: values,
				freeze: true,
				freeze_message: __('Creating Donor'),
			}).then((r) => {
				const result = r.message || {};
				if (result.donor) {
					dialog.hide();
					frappe.set_route('Form', 'Donor', result.donor);
				}
			});
		},
	});

	dialog.show();
}
