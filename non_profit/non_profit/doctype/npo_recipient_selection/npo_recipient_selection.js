frappe.ui.form.on("NPO Recipient Selection", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.page.add_action_item(__("Preview Recipients"), () => previewRecipients(frm));

		if (!frm.doc.enabled || frm.is_dirty()) return;
		if (!frm.doc.available_for_newsletter && !frm.doc.available_for_direct_mail) return;

		frm.page.add_action_item(__("Create Channel Campaigns"), () => {
			if (!window.npoChannelLaunch) {
				frappe.msgprint(__("The channel launcher is unavailable on this site."));
				return;
			}
			window.npoChannelLaunch.open(frm, {
				source_provider: "npo_recipient_selection",
				source_reference: frm.doc.name,
			});
		});
	},
});

async function previewRecipients(frm) {
	assertSaved(frm);
	const response = await frappe.call({
		method: "non_profit.non_profit.recipient_selection.preview_recipient_selection",
		type: "GET",
		args: { selection: frm.doc.name },
		freeze: true,
		freeze_message: __("Evaluating selection..."),
	});
	const result = response.message || { total: 0, rows: [] };
	const rows = result.rows
		.map(
			(row) => `<tr>
				<td>${frappe.utils.escape_html(row.subject_type || "")}</td>
				<td>${frappe.utils.escape_html(row.label || row.subject_name || "")}</td>
				<td>${frappe.utils.escape_html(row.email || "")}</td>
				<td>${frappe.utils.escape_html(row.language || "")}</td>
				<td>${row.postal_ready ? __("Yes") : __("No")}</td>
			</tr>`
		)
		.join("");
	const headerCells = [
		__("Type"),
		__("Recipient"),
		__("Email"),
		__("Language"),
		__("Postal Ready"),
	]
		.map((label) => `<th>${label}</th>`)
		.join("");
	const table = `<div class="table-responsive"><table class="table table-bordered">
			<thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table></div>`;
	frappe.msgprint({
		title: __("{0} Canonical Candidates", [result.total]),
		message: rows ? table : `<p>${__("No matching recipients.")}</p>`,
		wide: true,
	});
}

function assertSaved(frm) {
	if (frm.is_dirty()) {
		frappe.throw(__("Save the Recipient Selection before using this action."));
	}
}
