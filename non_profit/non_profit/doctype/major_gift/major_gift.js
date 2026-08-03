frappe.ui.form.on("Major Gift", {
	refresh(frm) {
		if (frm.is_new()) return;
		npo_add_action_item(frm, __("Set Next Action"), () =>
			npo_set_next_action(frm, frm.doc.relationship_manager)
		);
	},
});
