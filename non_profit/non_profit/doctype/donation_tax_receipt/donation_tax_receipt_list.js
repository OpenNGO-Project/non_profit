// Donation Tax Receipts are generated from the year's donations, never typed:
// every field on the DocType is read-only, so the standard "New" form is a dead
// end that only reports "Spender ist erforderlich / Steuerjahr ist erforderlich"
// for fields the user cannot fill. `generate_receipts` was whitelisted but had
// no caller in the UI, which left the batch reachable only from bench.
//
// This is that caller. Re-running is idempotent — unchanged Drafts are left
// alone and Issued receipts are never rewritten silently, they come back under
// `stale_issued` for manual amendment.

frappe.listview_settings["Donation Tax Receipt"] = {
	onload(listview) {
		set_generate_action(listview);
	},
	refresh(listview) {
		// The list re-renders its own actions on refresh; re-assert ours.
		set_generate_action(listview);
	},
};

function set_generate_action(listview) {
	listview.page.set_primary_action(
		__("Bescheinigungen erzeugen"),
		() => {
			const dialog = new frappe.ui.Dialog({
				title: __("Zuwendungsbestätigungen erzeugen"),
				fields: [
					{
						fieldtype: "Link",
						fieldname: "company",
						label: __("Unternehmen"),
						options: "Company",
						reqd: 1,
						default: frappe.defaults.get_user_default("Company"),
					},
					{
						fieldtype: "Int",
						fieldname: "tax_year",
						label: __("Steuerjahr"),
						reqd: 1,
						// The year just ended: receipts cover a completed
						// calendar year, so that is what an operator wants
						// almost every time they open this.
						default: new Date().getFullYear() - 1,
					},
					{
						fieldtype: "HTML",
						options: `<p class="text-muted small">${__(
							"Berücksichtigt werden gebuchte, bezahlte Spenden des gewählten Jahres mit hinterlegtem Spender."
						)}</p>`,
					},
				],
				primary_action_label: __("Erzeugen"),
				primary_action(values) {
					frappe.call({
						method: "non_profit.non_profit.tax_receipts.generate_receipts",
						args: values,
						freeze: true,
						freeze_message: __("Bescheinigungen werden erzeugt..."),
						callback(response) {
							dialog.hide();
							const report = response.message || {};
							const lines = [
								`${__("Neu erstellt")}: <b>${report.created || 0}</b>`,
								`${__("Aktualisiert")}: <b>${report.updated || 0}</b>`,
								`${__("Unverändert")}: <b>${report.unchanged || 0}</b>`,
								`${__("Entfernt")}: <b>${report.deleted || 0}</b>`,
							];
							if ((report.stale_issued || []).length) {
								lines.push(
									`${__(
										"Bereits ausgestellt und daher nicht überschrieben"
									)}: ${report.stale_issued.join(", ")}`
								);
							}
							frappe.msgprint({
								title: __("Zuwendungsbestätigungen {0}", [values.tax_year]),
								indicator: "green",
								message: lines.join("<br>"),
							});
							listview.refresh();
						},
					});
				},
			});
			dialog.show();
		},
		"add"
	);
}
