// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Donor", {
	refresh: function (frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: "name", doctype: "Donor" };

		frm.toggle_display(["address_html", "contact_html"], !frm.doc.__islocal);

		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);
			npo_add_action_item(frm, __("Set Next Action"), () =>
				npo_set_next_action(frm, frm.doc.relationship_manager)
			);

			frm.page.add_action_item(__("Accounting Ledger"), function () {
				if (frm.doc.customer) {
					frappe.set_route("query-report", "General Ledger", {
						party_type: "Customer",
						party: frm.doc.customer,
					});
				} else {
					frappe.set_route("query-report", "General Ledger", {
						party_type: "Donor",
						party: frm.doc.name,
					});
				}
			});

			// Deliberately outside the `frm.doc.customer` branch below: a
			// Zuwendungsbestätigung is owed to a donor whether or not anyone
			// ever created an ERPNext Customer for them.
			frm.page.add_action_item(__("Zuwendungsbestätigung erzeugen"), () =>
				generate_donor_tax_receipt(frm)
			);

			if (frm.doc.customer) {
				frm.page.add_action_item(__("Accounts Receivable"), function () {
					frappe.set_route("query-report", "Accounts Receivable", {
						customer: frm.doc.customer,
					});
				});
			}

			erpnext.utils.set_party_dashboard_indicators(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
			show_donor_creation_dialog(frm);
		}
	},
});

function show_donor_creation_dialog(frm) {
	if (frm.__donor_creation_dialog_shown) return;
	frm.__donor_creation_dialog_shown = true;

	const dialog = new frappe.ui.Dialog({
		title: __("Create Donor"),
		fields: [
			{
				fieldname: "contact",
				fieldtype: "Link",
				label: __("Contact"),
				options: "Contact",
			},
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
			},
			{
				fieldname: "donor_type",
				fieldtype: "Link",
				label: __("Donor Type"),
				options: "Donor Type",
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			if (!values.contact && !values.customer) {
				frappe.msgprint(__("Select a Contact or a Customer."));
				return;
			}

			frappe
				.call({
					method: "non_profit.non_profit.doctype.donor.donor.create_donor_from_identity",
					args: values,
					freeze: true,
					freeze_message: __("Creating Donor"),
				})
				.then((r) => {
					const result = r.message || {};
					if (result.donor) {
						dialog.hide();
						frappe.set_route("Form", "Donor", result.donor);
					}
				});
		},
	});

	dialog.show();
}

// The annual batch on the Donation Tax Receipt list is the normal route. This is
// the counter case: one donor asks for their Bescheinigung out of season, and
// re-running a whole year to answer them would be absurd. The server applies the
// same permissions, locking and reconciliation rules either way.
function generate_donor_tax_receipt(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Zuwendungsbestätigung für {0}", [frm.doc.donor_name || frm.doc.name]),
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
				default: new Date().getFullYear() - 1,
			},
		],
		primary_action_label: __("Erzeugen"),
		primary_action(values) {
			frappe.call({
				method: "non_profit.non_profit.tax_receipts.generate_receipt_for_donor",
				args: { donor: frm.doc.name, company: values.company, tax_year: values.tax_year },
				freeze: true,
				freeze_message: __("Bescheinigung wird erzeugt..."),
				callback(response) {
					dialog.hide();
					const report = response.message || {};
					if (report.receipt) {
						frappe.set_route("Form", "Donation Tax Receipt", report.receipt);
					} else {
						frappe.msgprint(__("Es wurde keine Bescheinigung erzeugt."));
					}
				},
			});
		},
	});
	dialog.show();
}
