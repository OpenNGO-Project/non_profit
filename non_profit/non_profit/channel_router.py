"""Neutral transactional channel router (revived Phase 5, minimal form).

Transactional 1:1 messages (donation thank-you, tax confirmation, …) have
been email-shaped with the channel choice implicit. This router revives the
dormant ``Donor.receipt_delivery`` preference as a *reader*: when a donor
explicitly prefers a channel registered through
``non_profit_transactional_channels`` and that channel accepts the flow,
the router hands the send to it; otherwise the caller keeps today's
behavior. Default preference values never change behavior — only an
explicit, registered-channel preference can.

Contract for a registered channel descriptor (dotted callables, same style
as ``channel_launch``)::

    {
        "key": "whatsapp",
        "label": "WhatsApp",
        "can_send": "app.module.can_send(flow, doc, profile) -> bool",
        "send": "app.module.send(flow, doc, context) -> dict",
    }

``profile`` is a small neutral dict (``donor``, ``contact``, ``language``).
``send`` must record its own auditable rows (e.g. message documents) and
must never raise for ordinary declining circumstances — returning normally
means "handled"; if the channel cannot send after all, it should return
``{"handled": False}`` so the caller falls back.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr

TRANSACTIONAL_CHANNEL_HOOK = "non_profit_transactional_channels"


def get_transactional_channels() -> list[dict[str, str]]:
	"""Resolved registered channels (dotted callables kept as paths)."""
	channels: list[dict[str, str]] = []
	for provider in frappe.get_hooks(TRANSACTIONAL_CHANNEL_HOOK) or []:
		descriptor = frappe.get_attr(provider)()
		if isinstance(descriptor, dict) and descriptor.get("key"):
			channels.append(descriptor)
	return channels


def donor_channel_preference(donor: str | None) -> str:
	"""The donor's ``receipt_delivery`` value (``""`` when unknown)."""
	donor = cstr(donor or "").strip()
	if not donor or not frappe.db.exists("Donor", donor):
		return ""
	return cstr(frappe.db.get_value("Donor", donor, "receipt_delivery") or "")


def _channel_profile(donor: str) -> dict[str, str]:
	contact = cstr(frappe.db.get_value("Donor", donor, "contact") or "")
	return {
		"donor": donor,
		"contact": contact,
		"language": cstr(frappe.db.get_value("Donor", donor, "preferred_language") or ""),
	}


def send_transactional(flow: str, doc: Any, context: dict | None = None) -> bool:
	"""Try the donor's preferred channel for one transactional flow.

	Returns ``True`` only when a registered channel reported the send handled;
	``False`` always means "run your default path" (no preference, unknown
	channel, or the channel declined).
	"""
	donor = cstr(getattr(doc, "donor", None) or "").strip()
	preference = donor_channel_preference(donor)
	if not preference:
		return False
	for channel in get_transactional_channels():
		if cstr(channel.get("key")).lower() != preference.lower():
			continue
		try:
			can_send = frappe.get_attr(channel["can_send"])
			send = frappe.get_attr(channel["send"])
			profile = _channel_profile(donor)
			if not can_send(flow=flow, doc=doc, profile=profile):
				return False
			result = send(flow=flow, doc=doc, context=dict(context or {}))
		except Exception:
			# A channel explosion must never break the caller's default path;
			# logging failures (e.g. inside patched test environments) neither.
			try:
				frappe.log_error(
					title=_("Transactional channel {0} failed for flow {1}").format(
						channel.get("key"), flow
					),
					message=frappe.get_traceback(),
				)
			except Exception:
				pass
			return False
		return bool(isinstance(result, dict) and result.get("handled", True))
	return False
