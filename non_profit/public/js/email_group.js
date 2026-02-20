frappe.ui.form.on("Email Group", {
	refresh: function (frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Import Subscribers with Filter"),
				function () {
					show_import_dialog(frm);
				},
				__("Action")
			);
		}

		frm.trigger("preview_welcome_url");
	},
	welcome_url(frm) {
		frm.trigger("preview_welcome_url");
	},
	add_query_parameters: function (frm) {
		frm.trigger("preview_welcome_url");
	},
	preview_welcome_url: function (frm) {
		if (frm.doc.add_query_parameters && frm.doc.welcome_url) {
			frm.call("preview_welcome_url", { email: "mail@example.org" }).then((r) => {
				frm.set_df_property(
					"add_query_parameters",
					"description",
					`${__("Preview:")} ${r.message}`
				);
			});
		} else {
			frm.set_df_property("add_query_parameters", "description", "");
		}
	},
});

function show_import_dialog(frm) {
	const import_options = [
		{ value: "records", label: __("Select Records") },
		{ value: "chapter", label: __("Import by Chapter") },
	];

	const dialog = new frappe.ui.Dialog({
		title: __("Import Subscribers"),
		fields: [
			{
				fieldname: "import_type",
				fieldtype: "Select",
				label: __("Import Method"),
				options: import_options,
				reqd: 1,
				default: "records",
				description: __("Select Records: Choose individual records to import. Import by Chapter: Import all members from a chapter and its subchapters."),
			},
		],
		primary_action_label: __("Continue"),
		primary_action: function (values) {
			dialog.hide();
			if (values.import_type === "chapter") {
				show_chapter_import_dialog(frm);
			} else {
				show_source_select_dialog(frm);
			}
		},
	});

	dialog.show();
}

function show_source_select_dialog(frm) {
	const doctype_options = [
		{ value: "Contact", label: __("Contact") },
		{ value: "Member", label: __("Member") },
		{ value: "Donor", label: __("Donor") },
		{ value: "Lead", label: __("Lead") },
	];

	const dialog = new frappe.ui.Dialog({
		title: __("Import Subscribers with Filter"),
		fields: [
			{
				fieldname: "source_doctype",
				fieldtype: "Select",
				label: __("Import From"),
				options: doctype_options,
				reqd: 1,
			},
		],
		primary_action_label: __("Select Records"),
		primary_action: function (values) {
			dialog.hide();
			show_multiselect_dialog(frm, values.source_doctype);
		},
	});

	dialog.show();
}

function show_chapter_import_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Import Members by Chapter"),
		fields: [
			{
				fieldname: "chapter",
				fieldtype: "Link",
				label: __("Chapter"),
				options: "Chapter",
				reqd: 1,
				description: __("All members from this chapter and its subchapters will be imported."),
			},
		],
		primary_action_label: __("Import"),
		primary_action: function (values) {
			frappe.call({
				method: "non_profit.non_profit.custom_doctype.email_group.import_members_by_chapter",
				args: {
					email_group: frm.doc.name,
					chapter: values.chapter,
				},
				callback: function (r) {
					if (r.message) {
						frappe.msgprint(__("{0} subscribers imported successfully.", [r.message]));
						frm.reload_doc();
					} else {
						frappe.msgprint(__("No new subscribers were imported."));
					}
				},
			});
			dialog.hide();
		},
	});

	dialog.show();
}

function show_multiselect_dialog(frm, source_doctype) {
	const setters = get_setters_for_doctype(source_doctype);
	const columns = get_columns_for_doctype(source_doctype);

	new frappe.ui.form.MultiSelectDialog({
		doctype: source_doctype,
		setters: setters,
		columns: columns,
		get_query: function () {
			return {
				filters: get_filters_for_doctype(source_doctype),
			};
		},
		add_filters_group: true,
		primary_action_label: __("Import Selected"),
		action: function (selected_documents, args) {
			if (!selected_documents || selected_documents.length === 0) {
				frappe.msgprint(__("Please select at least one record to import."));
				return;
			}

			frappe.call({
				method: "non_profit.non_profit.custom_doctype.email_group.import_selected_subscribers",
				args: {
					email_group: frm.doc.name,
					source_doctype: source_doctype,
					selected_records: selected_documents,
				},
				callback: function (r) {
					if (r.message) {
						frappe.msgprint(__("{0} subscribers imported successfully.", [r.message]));
						frm.reload_doc();
					}
				},
			});
		},
	});
}

function get_setters_for_doctype(doctype) {
	const setters_map = {
		Contact: [
			{ fieldname: "first_name", fieldtype: "Data", label: __("First Name") },
			{ fieldname: "email_id", fieldtype: "Data", label: __("Email") },
			{ fieldname: "status", fieldtype: "Select", label: __("Status"), options: "Passive\nOpen\nReplied" },
		],
		Member: [
			{ fieldname: "member_name", fieldtype: "Data", label: __("Member Name") },
			{ fieldname: "email_id", fieldtype: "Data", label: __("Email") },
			{ fieldname: "primary_chapter", fieldtype: "Link", label: __("Chapter"), options: "Chapter" },
			{ fieldname: "membership_type", fieldtype: "Link", label: __("Membership Type"), options: "Membership Type" },
		],
		Donor: [
			{ fieldname: "donor_name", fieldtype: "Data", label: __("Donor Name") },
			{ fieldname: "email", fieldtype: "Data", label: __("Email") },
			{ fieldname: "donor_type", fieldtype: "Link", label: __("Donor Type"), options: "Donor Type" },
		],
		Lead: [
			{ fieldname: "first_name", fieldtype: "Data", label: __("First Name") },
			{ fieldname: "email_id", fieldtype: "Data", label: __("Email") },
			{ fieldname: "status", fieldtype: "Select", label: __("Status") },
		],
	};

	return setters_map[doctype] || [];
}

function get_columns_for_doctype(doctype) {
	const columns_map = {
		Contact: ["name", "first_name", "last_name", "email_id"],
		Member: ["name", "member_name", "email_id", "primary_chapter"],
		Donor: ["name", "donor_name", "email", "donor_type"],
		Lead: ["name", "first_name", "last_name", "email_id", "status"],
	};

	return columns_map[doctype] || ["name"];
}

function get_filters_for_doctype(doctype) {
	const filters_map = {
		Contact: { email_id: ["!=", ""] },
		Member: { email_id: ["!=", ""] },
		Donor: { email: ["!=", ""] },
		Lead: { email_id: ["!=", ""] },
	};

	return filters_map[doctype] || {};
}
