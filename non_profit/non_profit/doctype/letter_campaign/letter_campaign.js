frappe.ui.form.on("Letter Campaign", {
	refresh: function (frm) {
		if (frm.doc.__islocal) {
			return;
		}

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(
				__("Add Recipients"),
				function () {
					show_recipient_dialog(frm);
				},
				__("Actions")
			);

			if (frm.doc.recipients && frm.doc.recipients.length > 0) {
				frm.add_custom_button(
					__("Generate PDFs"),
					function () {
						frappe.confirm(
							__("Generate PDFs for {0} recipients?", [frm.doc.total_recipients || 0]),
							function () {
								frm.call("generate_pdfs").then(function (r) {
									if (r.message) {
										frappe.msgprint(
											__("Generated {0} of {1} PDFs successfully.").format([
												r.message.generated,
												r.message.total,
											])
										);
										frm.reload_doc();
									}
								});
							}
						);
					},
					__("Actions")
				);
			}
		}

		if (frm.doc.status === "Generated" && frm.doc.generated_file) {
			frm.dashboard.set_headline(
				'<a href="' +
					frm.doc.generated_file +
					'" class="btn btn-sm btn-default" target="_blank">' +
					__("Download Generated File") +
					"</a>"
			);
		}
	},

	recipients_remove: function (frm) {
		frm.set_value("total_recipients", frm.doc.recipients ? frm.doc.recipients.length : 0);
	},
});

function show_recipient_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Recipients"),
		fields: [
			{
				fieldname: "source",
				fieldtype: "Select",
				label: __("Select Source"),
				options: [
					{ value: "Contact", label: __("Contact") },
					{ value: "Member", label: __("Member (by Membership Type)") },
				],
				reqd: 1,
				default: "Contact",
				onchange: function () {
					const source = this.get_value();
					dialog.fields_dict.membership_types.wrapper.toggle(source === "Member");
				},
			},
			{
				fieldname: "membership_types",
				fieldtype: "Link",
				label: __("Membership Type"),
				options: "Membership Type",
				hidden: 1,
			},
		],
		primary_action_label: __("Continue"),
		primary_action: function (values) {
			dialog.hide();

			if (values.source === "Contact") {
				show_contact_select_dialog(frm);
			} else {
				if (!values.membership_types) {
					frappe.msgprint(__("Please select a Membership Type"));
					return;
				}
				show_member_select_dialog(frm, [values.membership_types]);
			}
		},
	});

	dialog.show();
}

function show_contact_select_dialog(frm) {
	console.log("show_contact_select_dialog called");
	const d = new frappe.ui.form.MultiSelectDialog({
		doctype: "Contact",
		setters: {
			first_name: "",
			email_id: "",
		},
		columns: ["name", "full_name", "email_id"],
		get_query: function () {
			return {
				filters: {
					email_id: ["!=", ""],
				},
			};
		},
		add_filters_group: true,
		primary_action_label: __("Add Selected"),
		action: function (selections, args) {
			console.log("action called", selections, args);
			if (!selections || selections.length === 0) {
				frappe.msgprint(__("Please select at least one contact."));
				return;
			}

			frappe.call({
				method: "non_profit.non_profit.doctype.letter_campaign.letter_campaign.add_recipients",
				args: {
					campaign_name: frm.doc.name,
					source_doctype: "Contact",
					selected_records: selections,
				},
				callback: function (r) {
					console.log("response", r);
					if (r.message) {
						var msg = "";
						if (r.message.skipped > 0) {
							msg = __("Added {0} recipients. {1} contacts were skipped (no address found).").replace("{0}", r.message.added).replace("{1}", r.message.skipped);
						} else {
							msg = __("Added {0} recipients.").replace("{0}", r.message.added);
						}
						frappe.msgprint(msg);
						frm.reload_doc();
					}
				},
			});
		},
	});
	console.log("MultiSelectDialog created", d);
}

function show_member_select_dialog(frm, membership_types) {
	frappe.call({
		method: "non_profit.non_profit.doctype.letter_campaign.letter_campaign.get_members_by_membership_type",
		args: {
			membership_types: membership_types,
		},
		callback: function (r) {
			if (!r.message || r.message.length === 0) {
				frappe.msgprint(__("No members found with active memberships for the selected types."));
				return;
			}

			const members = r.message;
			const dialog = new frappe.ui.Dialog({
				title: __("Select Members"),
				size: "large",
				fields: [
					{
						fieldname: "members_html",
						fieldtype: "HTML",
						options: render_member_list(members),
					},
				],
				primary_action_label: __("Add Selected"),
				primary_action: function () {
					const selected = [];
					dialog.$wrapper.find(".member-checkbox:checked").each(function () {
						selected.push($(this).data("name"));
					});

					if (selected.length === 0) {
						frappe.msgprint(__("Please select at least one member."));
						return;
					}

					frappe.call({
						method: "non_profit.non_profit.doctype.letter_campaign.letter_campaign.add_recipients",
						args: {
							campaign_name: frm.doc.name,
							source_doctype: "Member",
							selected_records: selected,
						},
						callback: function (r) {
							if (r.message) {
								var msg = "";
								if (r.message.skipped > 0) {
									msg = __("Added {0} recipients. {1} members were skipped (no address found).").replace("{0}", r.message.added).replace("{1}", r.message.skipped);
								} else {
									msg = __("Added {0} recipients.").replace("{0}", r.message.added);
								}
								frappe.msgprint(msg);
								dialog.hide();
								frm.reload_doc();
							}
						},
					});
				},
			});

			dialog.show();

			dialog.$wrapper.find("#select_all_members").on("change", function () {
				const checked = $(this).prop("checked");
				dialog.$wrapper.find(".member-checkbox").prop("checked", checked);
			});
		},
	});
}

function render_member_list(members) {
	let html =
		'<div style="max-height: 400px; overflow-y: auto;">' +
		'<table class="table table-bordered table-hover">' +
		"<thead><tr>" +
		'<th style="width: 30px;"><input type="checkbox" id="select_all_members"></th>' +
		"<th>" +
		__("Member Name") +
		"</th>" +
		"<th>" +
		__("Email") +
		"</th>" +
		"</tr></thead><tbody>";

	members.forEach(function (member) {
		html +=
			"<tr>" +
			'<td><input type="checkbox" class="member-checkbox" data-name="' +
			member.name +
			'"></td>' +
			"<td>" +
			(member.member_name || member.name) +
			"</td>" +
			"<td>" +
			(member.email_id || "") +
			"</td>" +
			"</tr>";
	});

	html += "</tbody></table></div>";

	return html;
}
