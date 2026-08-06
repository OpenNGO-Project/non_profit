// Neutral multi-channel campaign launcher for saved NPO audience sources.
// Loaded desk-wide; saved audience source forms call window.npoChannelLaunch.open().
// Channel apps register fields via the
// non_profit_audience_channel_creators hook — this dialog stays generic.

frappe.provide("window.npoChannelLaunch");

window.npoChannelLaunch = {
	async open(frm, { source_provider, source_reference }) {
		const response = await frappe.call({
			method: "non_profit.non_profit.channel_launch.get_launch_form",
			type: "GET",
			args: { source_provider, source_reference },
			freeze: true,
			freeze_message: __("Loading campaign channels..."),
		});
		const form = response.message || {};
		const channels = form.channels || [];
		if (!channels.length) {
			frappe.msgprint(__("No campaign channel is available for this source."));
			return;
		}
		this.showDialog(frm, form.source, channels);
	},

	showDialog(frm, source, channels) {
		const sourceLabel = (source && source.source_label) || "";
		const fields = [
			{
				fieldname: "campaign_title",
				fieldtype: "Data",
				label: __("Campaign Title"),
				default: sourceLabel,
				reqd: 1,
			},
		];
		if (frappe.model.can_read("Donation Campaign")) {
			fields.push({
				fieldname: "donation_campaign",
				fieldtype: "Link",
				label: __("Donation Campaign"),
				options: "Donation Campaign",
				description: __("Optional umbrella campaign; attribution only."),
			});
		}
		fields.push({ fieldname: "channels_section", fieldtype: "Section Break", label: __("Channels") });

		const selectable = [];
		for (const channel of channels) {
			if (channel.requires_selection) {
				fields.push({
					fieldname: `${channel.key}_info`,
					fieldtype: "HTML",
					options: `<p class="text-muted small">${frappe.utils.escape_html(
						channel.description || channel.label
					)}</p>`,
				});
				continue;
			}
			selectable.push(channel);
			fields.push({
				fieldname: `channel_${channel.key}`,
				fieldtype: "Check",
				label: __(channel.label),
				description: channel.description || "",
			});
			const channelFields = (channel.fields || []).map((field) => {
				const channelCondition = `doc.channel_${channel.key}`;
				const qualifyCondition = (condition) =>
					(condition || "")
						.replace(/^eval:/, "")
						.replace(/doc\.([a-zA-Z0-9_]+)/g, `doc.${channel.key}__$1`);
				const copy = { ...field };
				if (!["Section Break", "Column Break", "HTML"].includes(field.fieldtype)) {
					copy.fieldname = `${channel.key}__${field.fieldname}`;
				}
				const fieldCondition = qualifyCondition(field.depends_on);
				copy.depends_on = `eval:${channelCondition}${fieldCondition ? ` && (${fieldCondition})` : ""}`;
				const mandatoryCondition = qualifyCondition(field.mandatory_depends_on);
				if (copy.reqd || mandatoryCondition) {
					delete copy.reqd;
					copy.mandatory_depends_on = `eval:${channelCondition}${
						mandatoryCondition ? ` && (${mandatoryCondition})` : ""
					}`;
				}
				if (copy.read_only_depends_on) {
					copy.read_only_depends_on = `eval:${qualifyCondition(copy.read_only_depends_on)}`;
				}
				return copy;
			});
			fields.push(...channelFields);
		}
		if (!selectable.length) {
			frappe.msgprint(__("No campaign channel is available for this source."));
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Create Channel Campaigns"),
			fields,
			primary_action_label: __("Create"),
			async primary_action(values) {
				const chosen = selectable.filter((channel) => values[`channel_${channel.key}`]);
				if (!chosen.length) {
					frappe.msgprint(__("Select at least one channel."));
					return;
				}
				const channel_values = {};
				for (const channel of chosen) {
					channel_values[channel.key] = {};
					for (const field of channel.fields || []) {
						if (["Section Break", "Column Break", "HTML"].includes(field.fieldtype)) continue;
						channel_values[channel.key][field.fieldname] =
							values[`${channel.key}__${field.fieldname}`];
					}
				}
				const required = channels
					.filter((channel) => channel.requires_selection)
					.map((channel) => channel.key);
				dialog.disable_primary_action();
				try {
					const response = await frappe.call({
						method: "non_profit.non_profit.channel_launch.create_channel_campaigns",
						args: {
							source_provider: source.source_provider,
							source_reference: source.source_reference,
							campaign_title: values.campaign_title,
							donation_campaign: values.donation_campaign || null,
							channels: [...required, ...chosen.map((channel) => channel.key)],
							channel_values,
						},
						freeze: true,
						freeze_message: __("Creating campaigns..."),
					});
					dialog.hide();
					const created = (response.message && response.message.campaigns) || [];
					const links = created
						.map(
							(campaign) =>
								`<li><a href="${frappe.utils.get_form_link(campaign.doctype, campaign.name)}">${frappe.utils.escape_html(
									campaign.label || campaign.name
								)}</a></li>`
						)
						.join("");
					frappe.msgprint({
						title: __("Campaigns Created"),
						message: `<ul>${links}</ul>`,
						indicator: "green",
						wide: true,
					});
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	},
};
