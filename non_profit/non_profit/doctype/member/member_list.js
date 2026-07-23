frappe.listview_settings["Member"] = {
	add_fields: ["member_name", "image"],
	primary_action() {
		show_member_creation_dialog();
	},
};

function show_member_creation_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Member and Membership"),
		fields: [
			{
				fieldname: "contact",
				fieldtype: "Link",
				label: __("Contact"),
				options: "Contact",
			},
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
			},
			{
				fieldname: "membership_type",
				fieldtype: "Link",
				label: __("Membership Type"),
				options: "Membership Type",
				reqd: 1,
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			const contact = values.contact || "";
			const customer = values.customer || "";
			if (!contact && !customer) {
				frappe.msgprint(__("Select a Contact or a Customer."));
				return;
			}

			frappe
				.call({
					method: "non_profit.non_profit.doctype.member.member.create_member_and_membership",
					args: values,
					freeze: true,
					freeze_message: __("Creating Member and Membership"),
				})
				.then((r) => {
					const result = r.message || {};
					if (result.member) {
						dialog.hide();
						frappe.set_route("Form", "Member", result.member);
					}
				});
		},
	});

	dialog.show();
}
