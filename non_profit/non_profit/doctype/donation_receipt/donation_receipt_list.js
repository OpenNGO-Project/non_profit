frappe.listview_settings["Donation Receipt"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Generate Yearly Receipts"), () => {
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
						default: "Germany",
						reqd: 1,
					},
				],
				(values) => {
					frappe.call({
						method: "non_profit.non_profit.doctype.donation_receipt.donation_receipt.generate_yearly_receipts",
						args: values,
						freeze: true,
						freeze_message: __("Generating receipts..."),
						callback: (r) => {
							frappe.msgprint(
								__("Created {0} receipts", [r.message.created])
							);
							listview.refresh();
						},
					});
				},
				__("Generate Yearly Receipts"),
				__("Generate")
			);
		});
	},
};
