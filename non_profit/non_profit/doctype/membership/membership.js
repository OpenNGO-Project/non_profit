// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Membership", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;

		frappe.meta.has_field(frm.doctype, "invoice") &&
			!frm.doc.invoice &&
			frm.page.add_action_item(__("Generate Invoice"), () => {
				frm.call({
					doc: frm.doc,
					method: "generate_invoice",
					args: { save: true },
					freeze: true,
					freeze_message: __("Creating Membership Invoice"),
					callback: function (r) {
						if (r.invoice) frm.reload_doc();
					},
				});
			});

		frappe.db.get_single_value("Non Profit Settings", "send_email").then((val) => {
			if (val)
				frm.page.add_action_item(__("Send Acknowledgement"), () => {
					frm.call("send_acknowlement").then(() => {
						frm.reload_doc();
					});
				});
		});
	},

	onload: function (frm) {
		frm.add_fetch("membership_type", "amount", "amount");
	},
});
