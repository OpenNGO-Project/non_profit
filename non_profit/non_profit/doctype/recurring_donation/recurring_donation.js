frappe.ui.form.on("Recurring Donation", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		const collecting = ["Active", "Payment Retrying", "Ending"].includes(frm.doc.status);
		const provider_managed = Boolean(
			frm.doc.payment_provider ||
				frm.doc.provider_subscription_id ||
				frm.doc.provider_reference ||
				frm.doc.provider_account
		);

		// Only meaningful when nothing external charges the schedule: a
		// provider-backed installment is recorded when the provider reports it.
		if (!provider_managed && frm.doc.status === "Active") {
			frm.page.add_action_item(__("Create Next Donation Now"), () => {
				frm.call("create_next_donation").then((r) => {
					frappe.msgprint(__("Created donation {0}", [r.message]));
					frm.reload_doc();
				});
			});
		}

		if (collecting) {
			frm.page.add_action_item(__("Change Amount"), () => {
				frappe.prompt(
					{
						fieldname: "amount",
						fieldtype: "Currency",
						label: __("New Amount"),
						reqd: 1,
						default: frm.doc.amount,
						description: __("Applies from the next charge, not the one already taken."),
					},
					({ amount }) => {
						frm.call("change_amount", { amount }).then(() => frm.reload_doc());
					},
					__("Change Amount")
				);
			});

			frm.page.add_action_item(__("Cancel Schedule"), () => {
				frappe.confirm(
					__("Stop future charges for this schedule? This takes effect immediately."),
					() => {
						frm.call("cancel_schedule").then(() => frm.reload_doc());
					}
				);
			});
		}

		if (
			frm.doc.status === "Pending Mandate" &&
			provider_managed &&
			!frm.doc.provider_subscription_id
		) {
			frm.page.add_action_item(__("Retire Abandoned Checkout"), () => {
				frappe.confirm(
					__(
						"Verify the current provider checkout and retire this Pending Mandate only if no subscription or payment can exist?"
					),
					() => {
						frm.call("retire_abandoned_pending_mandate").then(() => frm.reload_doc());
					}
				);
			});
		}

		if (frm.doc.status === "Payment Retrying") {
			frm.dashboard.set_headline_alert(
				__("A charge failed. {0} will try again — no action is needed yet.", [
					frm.doc.payment_provider || __("The provider"),
				]),
				"orange"
			);
		} else if (frm.doc.status === "Ending") {
			frm.dashboard.set_headline_alert(
				__("The donor cancelled. Remaining charges still follow."),
				"blue"
			);
		}
	},
});
