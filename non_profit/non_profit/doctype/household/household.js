// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Household", {
	refresh: function (frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: "name", doctype: "Household" };

		frm.toggle_display(["address_html", "contact_html"], !frm.doc.__islocal);

		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}
	},
});
