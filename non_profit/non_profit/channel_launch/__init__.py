"""Neutral multi-channel campaign launch for saved NPO audience sources.

`non_profit` owns the source forms and the umbrella Donation Campaign, but it
must not import private newsletter/direct-mail apps. Channel apps opt in through
the ``non_profit_audience_channel_creators`` hook; this module only validates
the source/common values, asks each selected channel for its Desk fields, and
invokes its creator inside one request transaction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _

CHANNEL_CREATOR_HOOK = "non_profit_audience_channel_creators"
SOURCE_PROVIDER_HOOK = "non_profit_audience_source_providers"
SELECTION_SOURCE_PROVIDER = "npo_recipient_selection"
ALLOWED_FIELD_TYPES = frozenset(
	{"Check", "Column Break", "Currency", "Data", "Date", "Link", "Select", "Section Break", "Small Text"}
)


@frappe.whitelist(methods=["GET"])
def get_launch_form(source_provider: str, source_reference: str) -> dict[str, Any]:
	"""Return channel descriptors and safe Desk field definitions for a source."""
	descriptor = _validate_source(source_provider, source_reference)
	channels = []
	for channel in _channel_creators().values():
		if not _channel_supports_source(channel, descriptor) or not _channel_is_available(
			channel, descriptor
		):
			continue
		fields = _normalized_launch_fields(channel)
		# A required infrastructure step (e.g. freezing a dynamic segment) has
		# no operator fields; ordinary channels with no fields are broken and
		# would only fail later, so omit them.
		if not fields and not channel.get("requires_selection"):
			continue
		channels.append(
			{
				"key": channel["key"],
				"label": channel["label"],
				"description": channel.get("description") or "",
				"fields": fields,
				"requires_selection": bool(channel.get("requires_selection")),
			}
		)
	return {"source": descriptor, "channels": channels}


@frappe.whitelist(methods=["POST"])
def create_channel_campaigns(
	source_provider: str,
	source_reference: str,
	campaign_title: str,
	donation_campaign: str | None = None,
	channels: list[str] | str | None = None,
	channel_values: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
	"""Create validated draft campaigns for selected registered channels."""
	descriptor = _validate_source(source_provider, source_reference)
	campaign_title = _required_text(campaign_title, _("Campaign Title is required."))
	donation_campaign = _optional_donation_campaign(donation_campaign)
	selected = _normalized_channel_keys(channels)
	values_by_channel = _normalized_channel_values(channel_values)
	creators = _channel_creators()
	missing_required = [
		channel["key"]
		for channel in creators.values()
		if channel.get("requires_selection")
		and _channel_supports_source(channel, descriptor)
		and channel["key"] not in selected
	]
	if missing_required:
		frappe.throw(_("This source requires the step {0}.").format(", ".join(missing_required)))

	required = [
		channel["key"]
		for channel in creators.values()
		if channel.get("requires_selection") and _channel_supports_source(channel, descriptor)
	]
	ordinary = [key for key in selected if key not in required]
	if not ordinary:
		frappe.throw(_("Select at least one campaign channel."))
	created = []
	launch_fingerprint = ""
	# Source-transform steps always run first, regardless of request ordering.
	# Subsequent channel creators must all receive the transformed descriptor.
	for key in [*required, *ordinary]:
		channel = creators.get(key)
		if channel is None:
			frappe.throw(_("Unknown campaign channel {0}.").format(key))
		if not _channel_supports_source(channel, descriptor):
			frappe.throw(_("{0} does not support this audience source.").format(channel.get("label") or key))
		if not _channel_is_available(channel, descriptor):
			frappe.throw(
				_("Campaign channel {0} is not available to you.").format(channel.get("label") or key),
				frappe.PermissionError,
			)
		values = values_by_channel.get(key, {})
		if not isinstance(values, dict):
			frappe.throw(_("Channel values for {0} must be an object.").format(key))
		if key not in required and not launch_fingerprint:
			launch_fingerprint = source_fingerprint(descriptor)
		creator = channel["create_campaign"]
		campaign = creator(
			descriptor=descriptor,
			campaign_title=campaign_title,
			donation_campaign=donation_campaign,
			source_fingerprint=launch_fingerprint,
			values=values,
		)
		# A source-owned creator may replace a Dynamic definition with its
		# newly frozen snapshot for every subsequent channel in this request.
		if isinstance(campaign, dict) and campaign.get("source"):
			descriptor = campaign["source"]
			campaign = campaign.get("campaign")
		if not campaign or not campaign.get("doctype") or not campaign.get("name"):
			frappe.throw(_("Campaign channel {0} returned an invalid result.").format(key))
		if not channel.get("requires_selection"):
			created.append(campaign)
	return {"campaigns": created}


def audience_channel_creator(
	key: str,
	label: str,
	launch_fields_path: str,
	create_campaign_path: str,
	is_available_path: str | None = None,
) -> dict:
	"""Build one channel-creator descriptor for a consuming app."""
	descriptor = {
		"key": key,
		"label": label,
		"launch_fields": launch_fields_path,
		"create_campaign": create_campaign_path,
	}
	if is_available_path:
		descriptor["is_available"] = is_available_path
	return descriptor


def source_fingerprint(descriptor: dict[str, Any]) -> str:
	"""Fingerprint the launch-time source definition/member state."""
	provider = descriptor["source_provider"]
	source = _source_providers().get(provider)
	if source is None:
		frappe.throw(_("Unsupported audience source provider {0}.").format(provider))
	payload = source["fingerprint_source"](descriptor)
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def audience_source_provider(
	key: str, validate_source_path: str, fingerprint_source_path: str
) -> dict[str, str]:
	"""Build one source-provider descriptor for an optional source app."""
	return {
		"key": key,
		"validate_source": validate_source_path,
		"fingerprint_source": fingerprint_source_path,
	}


def _channel_creators() -> dict[str, dict[str, Any]]:
	creators: dict[str, dict[str, Any]] = {}
	for path in frappe.get_hooks(CHANNEL_CREATOR_HOOK) or []:
		try:
			creator = frappe.get_attr(path)()
			creator = dict(creator)
			creator["launch_fields"] = frappe.get_attr(creator["launch_fields"])
			creator["create_campaign"] = frappe.get_attr(creator["create_campaign"])
			if creator.get("is_available"):
				creator["is_available"] = frappe.get_attr(creator["is_available"])
			creators[creator["key"]] = creator
		except Exception:
			frappe.log_error(title=f"NPO audience channel creator failed: {path}")
	return creators


def _source_providers() -> dict[str, dict[str, Any]]:
	providers = {
		SELECTION_SOURCE_PROVIDER: {
			"key": SELECTION_SOURCE_PROVIDER,
			"validate_source": _validate_recipient_selection_source,
			"fingerprint_source": _fingerprint_recipient_selection_source,
		}
	}
	for path in frappe.get_hooks(SOURCE_PROVIDER_HOOK) or []:
		try:
			provider = dict(frappe.get_attr(path)())
			provider["validate_source"] = frappe.get_attr(provider["validate_source"])
			provider["fingerprint_source"] = frappe.get_attr(provider["fingerprint_source"])
			providers[provider["key"]] = provider
		except Exception:
			frappe.log_error(title=f"NPO audience source provider failed: {path}")
	return providers


def _channel_supports_source(channel: dict[str, Any], descriptor: dict[str, Any]) -> bool:
	supports = channel.get("supports_source")
	if supports is not None:
		return bool(frappe.get_attr(supports)(descriptor))
	available = descriptor.get("available_channels")
	if available is not None and channel["key"] not in available and not channel.get("requires_selection"):
		return False
	return descriptor["source_provider"] in _source_providers()


def _channel_is_available(channel: dict[str, Any], descriptor: dict[str, Any]) -> bool:
	callback = channel.get("is_available")
	return True if callback is None else bool(callback(descriptor))


def _normalized_launch_fields(channel: dict[str, Any]) -> list[dict[str, Any]]:
	fields = channel["launch_fields"]()
	if not isinstance(fields, list):
		frappe.log_error(title=f"NPO audience channel fields failed: {channel['key']}")
		return []
	return [_normalized_field(channel, field) for field in fields]


def _normalized_field(channel: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(field, dict):
		frappe.throw(_("Campaign channel {0} returned an invalid field.").format(channel["key"]))
	fieldname = field.get("fieldname")
	fieldtype = field.get("fieldtype")
	if fieldtype not in ALLOWED_FIELD_TYPES or (
		fieldtype not in {"Column Break", "Section Break"} and not fieldname
	):
		frappe.throw(_("Campaign channel {0} returned an unsupported field.").format(channel["key"]))
	return dict(field)


def _validate_source(source_provider: str, source_reference: str) -> dict[str, Any]:
	provider = str(source_provider or "").strip()
	reference = str(source_reference or "").strip()
	source = _source_providers().get(provider)
	if source is None:
		frappe.throw(_("Unsupported audience source provider {0}.").format(provider))
	if not reference:
		frappe.throw(_("Select a saved audience source first."))
	descriptor = source["validate_source"](reference)
	if not isinstance(descriptor, dict):
		frappe.throw(_("Audience source provider {0} returned an invalid result.").format(provider))
	descriptor.update({"source_provider": provider, "source_reference": reference})
	return descriptor


def _validate_recipient_selection_source(reference: str) -> dict[str, Any]:
	selection = frappe.get_doc("NPO Recipient Selection", reference)
	selection.check_permission("read")
	if not selection.enabled:
		frappe.throw(_("Select an enabled Recipient Selection."))
	channels = [
		channel
		for channel, field in (
			("newsletter", "available_for_newsletter"),
			("direct_mail", "available_for_direct_mail"),
		)
		if selection.get(field)
	]
	return {
		"source_label": selection.selection_name or selection.name,
		"available_channels": channels,
	}


def _fingerprint_recipient_selection_source(descriptor: dict[str, Any]) -> dict[str, Any]:
	from non_profit.non_profit.recipient_selection import (
		evaluate_recipient_selection,
		get_recipient_selection_configuration,
	)

	selection = frappe.get_doc("NPO Recipient Selection", descriptor["source_reference"])
	selection.check_permission("read")
	return {
		"configuration": get_recipient_selection_configuration(selection),
		"rows": evaluate_recipient_selection(selection),
	}


def _optional_donation_campaign(value: str | None) -> str | None:
	name = str(value or "").strip()
	if not name:
		return None
	campaign = frappe.get_doc("Donation Campaign", name)
	campaign.check_permission("read")
	return campaign.name


def _normalized_channel_keys(values: list[str] | str | None) -> list[str]:
	parsed = frappe.parse_json(values) if isinstance(values, str) else values
	if not isinstance(parsed, list) or not parsed:
		frappe.throw(_("Select at least one campaign channel."))
	keys = []
	for value in parsed:
		key = str(value).strip()
		if key and key not in keys:
			keys.append(key)
	if not keys:
		frappe.throw(_("Select at least one campaign channel."))
	return keys


def _normalized_channel_values(values: dict[str, Any] | str | None) -> dict[str, Any]:
	parsed = frappe.parse_json(values) if isinstance(values, str) else values
	if parsed is None:
		return {}
	if not isinstance(parsed, dict):
		frappe.throw(_("Channel values must be an object."))
	return parsed


def _required_text(value: str, message: str) -> str:
	text = str(value or "").strip()
	if not text:
		frappe.throw(message)
	return text
