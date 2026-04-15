frappe.ui.form.on("Donation Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.email && !frm.doc.email_sent_on) {
			frm.add_custom_button(__("Send to Donor"), () => {
				frm.call("send_to_donor").then(() => {
					frappe.msgprint(__("Receipt sent to donor"));
					frm.reload_doc();
				});
			});
		}
	},
});
