// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Volunteer", {
	refresh: function (frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: "name", doctype: "Volunteer" };

		frm.toggle_display(["address_html", "contact_html"], !frm.doc.__islocal);

		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
			show_volunteer_creation_dialog(frm);
		}
	},
});

function show_volunteer_creation_dialog(frm) {
	if (frm.__volunteer_creation_dialog_shown) return;
	frm.__volunteer_creation_dialog_shown = true;

	const dialog = new frappe.ui.Dialog({
		title: __("Create Volunteer"),
		fields: [
			{
				fieldname: "contact",
				fieldtype: "Link",
				label: __("Contact"),
				options: "Contact",
				reqd: 1,
			},
			{
				fieldname: "volunteer_type",
				fieldtype: "Link",
				label: __("Volunteer Type"),
				options: "Volunteer Type",
				reqd: 1,
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			frappe
				.call({
					method: "non_profit.non_profit.doctype.volunteer.volunteer.create_volunteer_from_contact",
					args: values,
					freeze: true,
					freeze_message: __("Creating Volunteer"),
				})
				.then((r) => {
					const result = r.message || {};
					if (result.volunteer) {
						dialog.hide();
						frappe.set_route("Form", "Volunteer", result.volunteer);
					}
				});
		},
	});

	dialog.show();
}
