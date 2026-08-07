(() => {
	const outcomeActions = {
		"mark won": {
			fieldname: "won_reason",
			title: __("Why was this Major Gift won?"),
			label: __("Won Reason"),
			primaryAction: __("Mark Won"),
		},
		"mark lost": {
			fieldname: "lost_reason",
			title: __("Why was this Major Gift lost?"),
			label: __("Lost Reason"),
			primaryAction: __("Mark Lost"),
		},
	};

	frappe.ui.form.on("Major Gift", {
		refresh(frm) {
			setFollowUpDateEditability(frm);
			if (frm.is_new()) return;
			npo_add_action_item(frm, __("Set Next Action"), () =>
				npo_set_next_action(frm, frm.doc.relationship_manager)
			);
		},

		next_action_task: setFollowUpDateEditability,

		before_workflow_action(frm) {
			const action = (frm.selected_workflow_action || "").toLowerCase();
			const config = outcomeActions[action];
			if (!config) return Promise.resolve();
			return promptForOutcomeReason(frm, config);
		},
	});

	function setFollowUpDateEditability(frm) {
		frm.toggle_enable("next_action_date", !frm.doc.next_action_task);
	}

	function promptForOutcomeReason(frm, config) {
		frappe.dom?.unfreeze?.();
		// Core reloads the document before applying a workflow action, which drops
		// unsaved dialog values. The server wrapper injects the reason while still
		// delegating the state change to Frappe's standard workflow engine. Keep
		// this promise pending so the original handler does not apply it twice.
		return new Promise(() => {
			let handled = false;
			const dialog = new frappe.ui.Dialog({
				title: config.title,
				fields: [
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: config.label,
						reqd: 1,
						default: frm.doc[config.fieldname] || "",
					},
				],
				primary_action_label: config.primaryAction,
				primary_action(values) {
					dialog.disable_primary_action();
					frappe.dom?.freeze?.(__("Applying workflow action..."));
					frappe
						.xcall(
							"non_profit.non_profit.doctype.major_gift.major_gift.apply_outcome_workflow",
							{
								name: frm.docname,
								action: frm.selected_workflow_action,
								reason: values.reason.trim(),
							},
							"POST"
						)
						.then(async (doc) => {
							handled = true;
							dialog.hide();
							frappe.model.sync(doc);
							frm._wv_centered_once = false;
							await frm.refresh();
							frm.selected_workflow_action = null;
							await frm.script_manager.trigger("after_workflow_action");
							frappe.show_alert({
								message: __("Moved to {0}", [frm.doc.stage]),
								indicator: "green",
							});
						})
						.catch((error) => {
							dialog.enable_primary_action();
							console.error(error);
						})
						.finally(() => {
							frappe.dom?.unfreeze?.();
						});
				},
				secondary_action_label: __("Cancel"),
				secondary_action() {
					handled = true;
					dialog.hide();
					abortWorkflowAction(frm);
				},
			});
			dialog.onhide = () => {
				if (!handled) abortWorkflowAction(frm);
			};
			dialog.show();
		});
	}

	function abortWorkflowAction(frm) {
		frm.selected_workflow_action = null;
		frappe.dom?.unfreeze?.();
	}
})();
