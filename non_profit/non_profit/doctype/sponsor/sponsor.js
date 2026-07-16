frappe.ui.form.on('Sponsor', {
	refresh(frm) {
		if (frm.doc.__islocal) {
			show_sponsor_creation_dialog(frm);
		}
	},
});

function show_sponsor_creation_dialog(frm) {
	if (frm.__sponsor_creation_dialog_shown) return;
	frm.__sponsor_creation_dialog_shown = true;

	const dialog = new frappe.ui.Dialog({
		title: __('Create Sponsor'),
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
			{
				fieldname: 'tier',
				fieldtype: 'Link',
				label: __('Sponsor Tier'),
				options: 'Sponsor Tier',
			},
		],
		primary_action_label: __('Create'),
		primary_action(values) {
			if (!values.contact && !values.customer) {
				frappe.msgprint(__('Select a Contact or a Customer.'));
				return;
			}

			frappe.call({
				method: 'non_profit.non_profit.doctype.sponsor.sponsor.create_sponsor_from_identity',
				args: values,
				freeze: true,
				freeze_message: __('Creating Sponsor'),
			}).then((r) => {
				const result = r.message || {};
				if (result.sponsor) {
					dialog.hide();
					frappe.set_route('Form', 'Sponsor', result.sponsor);
				}
			});
		},
	});

	dialog.show();
}
