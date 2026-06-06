frappe.ui.form.on("Donation Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.page.add_action_item(__("Spenden aus Geschäftsjahr hinzufügen"), () => {
				if (!frm.doc.fiscal_year || !frm.doc.donor) {
					frappe.msgprint(__("Bitte Spender und Geschäftsjahr auswählen."));
					return;
				}

				frappe.call({
					method: "non_profit.non_profit.doctype.donation_receipt.donation_receipt.get_donations_for_selected_year",
					args: {
						fiscal_year: frm.doc.fiscal_year,
						donor: frm.doc.donor,
					},
					freeze: true,
					freeze_message: __("Spenden werden geladen..."),
				}).then((r) => {
					const rows = (r.message && r.message.donations) || [];
					frm.clear_table("donations");
					rows.forEach((donation) => {
						const row = frm.add_child("donations");
						row.donation = donation.donation;
						row.donation_date = donation.donation_date;
						row.amount = donation.amount;
					});
					frm.refresh_field("donations");
					frm.dirty();
					frappe.show_alert(
						__("{0} Spenden hinzugefügt", [rows.length])
					);
				});
			});
		}

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
