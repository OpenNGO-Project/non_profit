// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Volunteer', {
	refresh: function(frm) {
		// No more Dynamic Link pattern
	},

	contact: function(frm) {
		if (frm.doc.contact) {
			frappe.db.get_value("Contact", frm.doc.contact, ["email_id"])
				.then(r => {
					if (r.message) {
						frm.set_value("email", r.message.email_id);
					}
				});
		} else {
			frm.set_value("email", "");
		}
	}
});
