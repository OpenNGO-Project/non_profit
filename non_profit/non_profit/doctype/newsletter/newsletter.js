frappe.ui.form.on("Newsletter", {
	refresh: function (frm) {
		frm.trigger("set_sender_options");
		frm.trigger("update_recipient_count_display");
		frm.trigger("add_custom_buttons");
		frm.trigger("show_email_queue_link");
	},

	set_sender_options: function (frm) {
		frappe.call({
			method: "non_profit.non_profit.doctype.newsletter.newsletter.get_email_accounts",
			callback: function (r) {
				if (r.message && r.message.length > 0) {
					frm.set_df_property("sender", "options", r.message.join("\n"));
				}
			},
		});
	},

	update_recipient_count_display: function (frm) {
		if (frm.doc.email_groups && frm.doc.email_groups.length > 0) {
			frappe.call({
				method: "non_profit.non_profit.doctype.newsletter.newsletter.get_recipient_count",
				args: {
					email_groups: frm.doc.email_groups,
				},
				callback: function (r) {
					if (r.message !== undefined) {
						frm.set_value("total_recipients", r.message);
					}
				},
			});
		} else {
			frm.set_value("total_recipients", 0);
		}
	},

	email_groups_add: function (frm) {
		frm.trigger("update_recipient_count_display");
	},

	email_groups_remove: function (frm) {
		frm.trigger("update_recipient_count_display");
	},

	email_template: function (frm) {
		if (frm.doc.email_template) {
			frappe.call({
				method: "non_profit.non_profit.doctype.newsletter.newsletter.get_template_content",
				args: {
					template_name: frm.doc.email_template,
				},
				callback: function (r) {
					if (r.message) {
						if (!frm.doc.subject) {
							frm.set_value("subject", r.message.subject);
						}
						if (!frm.doc.content && !frm.doc.use_html) {
							frm.set_value("content", r.message.content);
						}
						if (!frm.doc.html_content && r.message.use_html) {
							frm.set_value("use_html", 1);
							frm.set_value("html_content", r.message.html_content);
						}
					}
				},
			});
		}
	},

	add_custom_buttons: function (frm) {
		if (frm.doc.__islocal) {
			return;
		}

		if (frm.doc.status === "Draft" || frm.doc.status === "Failed") {
			frm.add_custom_button(__("Send Now"), function () {
				frappe.confirm(
					__(
						"This will send the newsletter to {0} recipients. Continue?",
						[frm.doc.total_recipients || 0]
					),
					function () {
						frm.call("send_now").then(function () {
							frm.refresh();
						});
					}
				);
			}).addClass("btn-primary");

			if (frm.doc.schedule_send && frm.doc.send_after) {
				frm.add_custom_button(__("Schedule Send"), function () {
					frm.call("schedule").then(function () {
						frm.refresh();
					});
				});
			}
		}
	},

	show_email_queue_link: function (frm) {
		if (frm.doc.__islocal || frm.doc.status === "Draft") {
			return;
		}

		frappe.db.get_list("Email Queue", {
			filters: {
				reference_doctype: "Newsletter",
				reference_name: frm.doc.name,
			},
			fields: ["name", "status", "creation"],
			limit: 5,
		}).then(function (records) {
			if (records.length > 0) {
				let html =
					'<div class="email-queue-links"><p><strong>' +
					__("Recent Email Queue Entries") +
					"</strong></p><ul>";

				records.forEach(function (record) {
					html +=
						'<li><a href="/app/email-queue/' +
						record.name +
						'">' +
						record.name +
						"</a> - " +
						record.status +
						" (" +
						frappe.datetime.comment_when(record.creation) +
						")</li>";
				});

				html += "</ul></div>";
				$(frm.fields_dict.email_queue_link.wrapper).html(html);
			}
		});
	},

	schedule_send: function (frm) {
		if (frm.doc.schedule_send && !frm.doc.send_after) {
			frm.set_value("send_after", frappe.datetime.add_hours(frappe.datetime.now_datetime(), 1));
		}
	},
});
