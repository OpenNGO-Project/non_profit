frappe.listview_settings["Donation Receipt"] = {
	onload(listview) {
		listview.page.add_action_item(__("Jährliche Spendenbescheinigungen erstellen"), () => {
			frappe.prompt(
				[
					{
						fieldname: "fiscal_year",
						label: __("Fiscal Year"),
						fieldtype: "Link",
						options: "Fiscal Year",
						reqd: 1,
					},
					{
						fieldname: "country",
						label: __("Country"),
						fieldtype: "Link",
						options: "Country",
						default: "Switzerland",
						reqd: 1,
					},
				],
				(values) => {
					frappe.call({
						method: "non_profit.non_profit.doctype.donation_receipt.donation_receipt.generate_yearly_receipts",
						args: values,
						callback: (r) => {
							frappe.msgprint(
								__("Die Erstellung wurde als Hintergrundauftrag eingereiht: {0}", [
									r.message.job_id,
								])
							);
						},
					});
				},
				__("Jährliche Spendenbescheinigungen erstellen"),
				__("Erstellen")
			);
		});
	},
};
