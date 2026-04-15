frappe.ui.form.on("Recurring Donation", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.status === "Active") {
			frm.add_custom_button(__("Create Next Donation Now"), () => {
				frm.call("create_next_donation").then((r) => {
					frappe.msgprint(__("Created donation {0}", [r.message]));
					frm.reload_doc();
				});
			});
		}
	},
});
