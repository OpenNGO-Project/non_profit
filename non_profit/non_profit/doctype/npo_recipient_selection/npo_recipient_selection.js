frappe.ui.form.on("NPO Recipient Selection", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.page.add_action_item(__("Preview Recipients"), () => previewRecipients(frm));

		if (
			frm.doc.enabled &&
			frm.doc.available_for_newsletter &&
			frappe.model.can_create("Good Newsletter Campaign") &&
			frappe.model.can_create("Good Newsletter Audience")
		) {
			frm.page.add_action_item(__("Create Newsletter Campaign"), () =>
				createNewsletterCampaign(frm)
			);
		}

		if (
			frm.doc.enabled &&
			frm.doc.available_for_direct_mail &&
			frappe.model.can_create("Good Direct Mail Campaign")
		) {
			frm.page.add_action_item(__("Create Direct Mail Run"), () => {
				assertSaved(frm);
				frappe.new_doc("Good Direct Mail Campaign", {
					recipient_selection: frm.doc.name,
					title: frm.doc.selection_name,
				});
			});
		}
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
	frappe.msgprint({
		title: __("{0} Canonical Candidates", [result.total]),
		message: rows
			? `<div class="table-responsive"><table class="table table-bordered">
				<thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p>${__("No matching recipients.")}</p>`,
		wide: true,
	});
}

function createNewsletterCampaign(frm) {
	assertSaved(frm);
	const dialog = new frappe.ui.Dialog({
		title: __("Create Newsletter Campaign"),
		fields: [
			{
				fieldname: "campaign_title",
				fieldtype: "Data",
				label: __("Campaign Title"),
				default: frm.doc.selection_name,
				reqd: 1,
			},
			{
				fieldname: "subject",
				fieldtype: "Data",
				label: __("Subject"),
				default: frm.doc.selection_name,
				reqd: 1,
			},
			{
				fieldname: "as_pending",
				fieldtype: "Check",
				label: __("Import as Pending (require opt-in confirmation)"),
				description: __(
					"Leave unchecked only when an existing consent or relationship permits mailing."
				),
			},
		],
		primary_action_label: __("Create Campaign"),
		async primary_action(values) {
			dialog.disable_primary_action();
			try {
				const response = await frappe.call({
					method: "good_newsletter.api.campaign.create_from_source",
					args: {
						provider: "npo_recipient_selection",
						source: frm.doc.name,
						campaign_title: values.campaign_title,
						subject: values.subject,
						as_pending: values.as_pending ? 1 : 0,
					},
					freeze: true,
					freeze_message: __("Creating newsletter campaign..."),
				});
				dialog.hide();
				const result = response.message || {};
				frappe.set_route("Form", "Good Newsletter Campaign", result.campaign);
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.show();
}

function assertSaved(frm) {
	if (frm.is_dirty()) {
		frappe.throw(__("Save the Recipient Selection before using this action."));
	}
}
