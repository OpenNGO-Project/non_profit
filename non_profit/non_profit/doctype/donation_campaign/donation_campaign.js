frappe.ui.form.on("Donation Campaign", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh Totals"), () => {
				frm.call("refresh_totals").then(() => frm.reload_doc());
			});
		}
	},
});
