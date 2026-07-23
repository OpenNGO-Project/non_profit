// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Donation", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.paid) {
			frm.page.add_action_item(__("Create Payment Entry"), function () {
				frm.events.make_payment_entry(frm);
			});
		}
		if (frm.doc.docstatus === 1 && frm.doc.paid && !frm.doc.thank_you_sent) {
			if (frm.doc.email) {
				frm.page.add_action_item(__("Verdankung senden"), function () {
					frm.call("send_thank_you").then(function () {
						frappe.msgprint(__("Verdankung gesendet."));
						frm.reload_doc();
					});
				});
			}
			frm.page.add_action_item(__("Als extern verdankt markieren"), function () {
				frm.call("mark_thank_you_sent").then(function () {
					frappe.msgprint(__("Spende als extern verdankt markiert."));
					frm.reload_doc();
				});
			});
		}
	},

	make_payment_entry: function (frm) {
		return frappe.call({
			method: "non_profit.non_profit.custom_doctype.payment_entry.get_donation_payment_entry",
			args: {
				dt: frm.doc.doctype,
				dn: frm.doc.name,
			},
			callback: function (r) {
				var doc = frappe.model.sync(r.message);
				frappe.set_route("Form", doc[0].doctype, doc[0].name);
			},
		});
	},
});
