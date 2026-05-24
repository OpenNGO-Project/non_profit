frappe.ui.form.on("Donation Campaign", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.page.add_action_item(__("Refresh Totals"), () => {
				frm.call("refresh_totals").then(() => frm.reload_doc());
			});
		}
	},
});
