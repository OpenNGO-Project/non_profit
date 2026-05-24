frappe.ui.form.on("Donation Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.email && !frm.doc.email_sent_on) {
			frm.page.add_action_item(__("Spendenbescheinigung senden"), () => {
				frm.call("send_to_donor").then(() => {
					frappe.msgprint(__("Spendenbescheinigung gesendet."));
					frm.reload_doc();
				});
			});
		}
	},
});
