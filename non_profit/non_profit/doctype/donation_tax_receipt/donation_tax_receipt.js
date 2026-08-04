frappe.ui.form.on("Donation Tax Receipt", {
	refresh(frm) {
		if (frm.is_new() || !["Draft", "Issued"].includes(frm.doc.status)) {
			return;
		}

		frm.page.add_action_item(__("Spendenbescheinigung per E-Mail senden"), () => {
			frappe.confirm(
				__("Die Spendenbescheinigung {0} als PDF an die Spenderin / den Spender senden?", [
					frm.doc.name,
				]),
				() => {
					frappe
						.call({
							method: "non_profit.non_profit.tax_receipts.send_receipt_email",
							type: "POST",
							args: { receipt: frm.doc.name },
							freeze: true,
							freeze_message: __("Spendenbescheinigung wird gesendet..."),
						})
						.then((r) => {
							if (!r.message) return;
							frappe.msgprint(
								__("Spendenbescheinigung an {0} gesendet.", [r.message.email])
							);
							frm.reload_doc();
						});
				}
			);
		});

		frm.page.add_action_item(__("Spendenbescheinigung stornieren"), () => {
			frappe.prompt(
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Stornierungsgrund"),
					reqd: 1,
				},
				({ reason }) => {
					frappe
						.call({
							method: "non_profit.non_profit.tax_receipts.cancel_receipt",
							type: "POST",
							args: { receipt: frm.doc.name, reason },
							freeze: true,
							freeze_message: __("Spendenbescheinigung wird storniert..."),
						})
						.then(() => frm.reload_doc());
				},
				__("Spendenbescheinigung stornieren")
			);
		});
	},
});
