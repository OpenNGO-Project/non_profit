frappe.ui.form.on("Major Gift", {
	refresh(frm) {
		if (frm.is_new()) return;
		npo_add_action_item(frm, __("Set Next Action"), () =>
			npo_set_next_action(frm, frm.doc.relationship_manager)
		);
	},
});

function npo_set_next_action(frm, defaultAssignee) {
	frappe.prompt(
		[
			{ fieldtype: "Small Text", fieldname: "subject", label: __("Next Action"), reqd: 1 },
			{ fieldtype: "Date", fieldname: "due_date", label: __("Due Date") },
			{
				fieldtype: "Link",
				fieldname: "assignee",
				label: __("Assign To"),
				options: "User",
				default: defaultAssignee || frappe.session.user,
			},
		],
		(values) => {
			frappe.call({
				method: "non_profit.non_profit.next_actions.set_next_action",
				args: {
					doctype: frm.doctype,
					name: frm.docname,
					subject: values.subject,
					due_date: values.due_date,
					assignee: values.assignee,
				},
				freeze: true,
				freeze_message: __("Creating next-action task..."),
				callback: (response) => {
					const result = response.message || {};
					if (result.task) {
						frappe.show_alert({
							message: __("Next action task {0} created.", [result.task]),
							indicator: "green",
						});
					}
					frm.reload_doc();
				},
			});
		},
		__("Set Next Action"),
		__("Create Task")
	);
}

function npo_add_action_item(frm, label, action) {
	if (!frm.page?.actions) return;
	npo_remove_action_item(frm, label);
	frm.page.add_action_item(label, action);
}

function npo_remove_action_item(frm, label) {
	if (!frm.page?.actions) return;
	frm.page.actions
		.find("li > a.dropdown-item")
		.filter(function () {
			return $(this).find(".menu-item-label").text().trim() === label;
		})
		.parent()
		.remove();
}
