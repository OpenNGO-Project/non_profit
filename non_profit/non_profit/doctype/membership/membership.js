frappe.ui.form.on('Membership', {
	setup: function(frm) {
		frappe.db.get_single_value("Non Profit Settings", "enable_razorpay_for_memberships").then(val => {
			if (val) frm.set_df_property("razorpay_details_section", "hidden", false);
		})
	},

	refresh: function(frm) {
		if (frm.doc.__islocal)
			return;

		!frm.doc.invoice && frm.add_custom_button("Generate Invoice", () => {
			frm.call({
				doc: frm.doc,
				method: "generate_invoice",
				args: {save: true},
				freeze: true,
				freeze_message: __("Creating Membership Invoice"),
				callback: function(r) {
					if (r.invoice)
						frm.reload_doc();
				}
			});
		});

		frappe.db.get_single_value("Non Profit Settings", "send_email").then(val => {
			if (val) frm.add_custom_button("Send Acknowledgement", () => {
				frm.call("send_acknowlement").then(() => {
					frm.reload_doc();
				});
			});
		})

		frm.trigger('set_indicator');
	},

	set_indicator: function(frm) {
		if (frm.doc.subscription) {
			frappe.db.get_value('Subscription', frm.doc.subscription, 'status').then(r => {
				if (r && r.message) {
					let status = r.message.status;
					let indicator = membership_get_status_indicator(status);
					frm.page.set_indicator(indicator.label, indicator.color);
				}
			});
		} else if (frm.doc.docstatus === 1) {
			frm.page.set_indicator(__('Active'), 'blue');
		}
	},

	onload: function(frm) {
		frm.add_fetch("membership_type", "amount", "amount");
	}
});

function membership_get_status_indicator(status) {
	const status_map = {
		'Active': {label: __('Active'), color: 'green'},
		'Trialing': {label: __('New'), color: 'blue'},
		'Grace Period': {label: __('Pending'), color: 'orange'},
		'Unpaid': {label: __('Expired'), color: 'red'},
		'Cancelled': {label: __('Cancelled'), color: 'red'},
		'Completed': {label: __('Expired'), color: 'grey'},
	};
	return status_map[status] || {label: status || __('Unknown'), color: 'grey'};
}
