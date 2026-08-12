# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tribute-gift validation and explicit fulfillment state.

This module stores notification instructions on the Donation itself. It never
creates Contact or Address masters and never sends a notification implicitly.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, now_datetime, validate_email_address

FULFILLMENT_STATUSES = ("Not Requested", "Pending", "Fulfilled", "Unable")
TERMINAL_FULFILLMENT_STATUSES = ("Fulfilled", "Unable")
FULFILLMENT_FIELDS = (
	"tribute_fulfillment_status",
	"tribute_fulfilled_on",
	"tribute_fulfilled_by",
	"tribute_fulfillment_note",
)
TRIBUTE_DEFINITION_FIELDS = (
	"tribute_type",
	"tribute_honouree",
	"tribute_notification_requested",
	"tribute_notification_name",
	"tribute_notification_contact",
	"tribute_notification_email",
	"tribute_notification_address",
	"tribute_notification_address_text",
	"tribute_notification_message",
)

_FULFILLMENT_WRITE_CAPABILITY = object()


def public_tribute_values(
	*,
	tribute_type: str | None = None,
	honouree: str | None = None,
	notification_requested: str | int | bool | None = None,
	notification_name: str | None = None,
	notification_email: str | None = None,
	notification_address: str | None = None,
	notification_message: str | None = None,
) -> dict:
	"""Validate guest tribute snapshots without touching identity master data."""
	tribute_type = normalize_tribute_type(tribute_type)
	honouree = _bounded_text(honouree, 140, _("Honouree"))
	notification_name = _bounded_text(notification_name, 140, _("Notification Recipient"))
	notification_email = cstr(notification_email).strip().lower()
	notification_address = _bounded_text(notification_address, 1000, _("Notification Address"))
	notification_message = _bounded_text(notification_message, 1000, _("Tribute Message"))
	notification_requested = cint(notification_requested)

	if not tribute_type:
		if any(
			(
				honouree,
				notification_requested,
				notification_name,
				notification_email,
				notification_address,
				notification_message,
			)
		):
			frappe.throw(_("Select a tribute type before entering tribute details."))
		return {}

	if not honouree:
		frappe.throw(_("Honouree is required for a tribute gift."))
	if notification_email:
		validate_email_address(notification_email, throw=True)
	if notification_requested:
		if not notification_name:
			frappe.throw(_("Notification Recipient is required when a notification is requested."))
		if not notification_email and not notification_address:
			frappe.throw(_("Enter a notification email or postal address."))
	elif any((notification_name, notification_email, notification_address, notification_message)):
		frappe.throw(_("Request a tribute notification before entering recipient details."))

	return {
		"tribute_type": tribute_type,
		"tribute_honouree": honouree,
		"tribute_notification_requested": notification_requested,
		"tribute_notification_name": notification_name or None,
		"tribute_notification_email": notification_email or None,
		"tribute_notification_address_text": notification_address or None,
		"tribute_notification_message": notification_message or None,
		"tribute_fulfillment_status": "Pending" if notification_requested else "Not Requested",
	}


def normalize_tribute_type(value: str | None) -> str:
	value = cstr(value).strip()
	if not value:
		return ""
	normalized = value.lower().replace("-", " ").replace("_", " ")
	aliases = {
		"honour": "In Honour",
		"honor": "In Honour",
		"in honour": "In Honour",
		"in honor": "In Honour",
		"memory": "In Memory",
		"in memory": "In Memory",
	}
	if normalized not in aliases:
		frappe.throw(_("Unsupported tribute type."))
	return aliases[normalized]


def validate_tribute(donation) -> None:
	"""Enforce Donation-level tribute and fulfillment invariants."""
	_before = donation.get_doc_before_save()
	_validate_fulfillment_write(donation, _before)

	donation.tribute_type = normalize_tribute_type(donation.get("tribute_type"))
	if not donation.tribute_type:
		if any(donation.get(fieldname) for fieldname in TRIBUTE_DEFINITION_FIELDS[1:]):
			frappe.throw(_("Select a tribute type before entering tribute details."))
		donation.tribute_fulfillment_status = "Not Requested"
		_validate_fulfillment_audit(donation)
		return

	if not cstr(donation.tribute_honouree).strip():
		frappe.throw(_("Honouree is required for a tribute gift."))
	if donation.tribute_notification_email:
		validate_email_address(cstr(donation.tribute_notification_email).strip(), throw=True)

	requested = cint(donation.tribute_notification_requested)
	if requested:
		if not cstr(donation.tribute_notification_name).strip():
			frappe.throw(_("Notification Recipient is required when a notification is requested."))
		if not any(
			donation.get(fieldname)
			for fieldname in (
				"tribute_notification_contact",
				"tribute_notification_email",
				"tribute_notification_address",
				"tribute_notification_address_text",
			)
		):
			frappe.throw(_("Enter a notification contact, email, or postal address."))
		if donation.tribute_fulfillment_status in (None, "", "Not Requested"):
			donation.tribute_fulfillment_status = "Pending"
	else:
		if any(donation.get(fieldname) for fieldname in TRIBUTE_DEFINITION_FIELDS[3:]):
			frappe.throw(_("Request a tribute notification before entering recipient details."))
		donation.tribute_fulfillment_status = "Not Requested"

	_validate_fulfillment_audit(donation)


def set_tribute_fulfillment(
	donation_name: str,
	status: str,
	*,
	note: str | None = None,
):
	"""Record staff fulfillment without sending or mutating recipient masters."""
	donation = frappe.get_doc("Donation", donation_name, for_update=True)
	donation.check_permission("write")
	status = cstr(status).strip()
	if status not in TERMINAL_FULFILLMENT_STATUSES:
		frappe.throw(_("Tribute fulfillment must be marked Fulfilled or Unable."))
	if donation.docstatus != 1 or not cint(donation.paid):
		frappe.throw(_("Only a submitted, paid Donation can fulfill a tribute notification."))
	if not donation.tribute_type or not cint(donation.tribute_notification_requested):
		frappe.throw(_("This Donation has no requested tribute notification."))
	for doctype, fieldname in (
		("Contact", "tribute_notification_contact"),
		("Address", "tribute_notification_address"),
	):
		if name := donation.get(fieldname):
			frappe.get_doc(doctype, name).check_permission("read")
	if donation.tribute_fulfillment_status in TERMINAL_FULFILLMENT_STATUSES:
		if donation.tribute_fulfillment_status == status:
			return donation
		frappe.throw(_("This tribute notification already has a terminal fulfillment state."))

	note = _bounded_text(note, 1000, _("Fulfillment Note"))
	if status == "Unable" and not note:
		frappe.throw(_("A fulfillment note is required when the notification cannot be fulfilled."))
	donation.tribute_fulfillment_status = status
	donation.tribute_fulfilled_on = now_datetime()
	donation.tribute_fulfilled_by = frappe.session.user
	donation.tribute_fulfillment_note = note or None
	donation.flags.tribute_fulfillment_capability = _FULFILLMENT_WRITE_CAPABILITY
	donation.save()
	return donation


def _validate_fulfillment_write(donation, before) -> None:
	if not before:
		status = cstr(donation.tribute_fulfillment_status).strip()
		if status in TERMINAL_FULFILLMENT_STATUSES or any(
			donation.get(fieldname) for fieldname in FULFILLMENT_FIELDS[1:]
		):
			frappe.throw(_("Tribute fulfillment audit can only be set through the fulfillment action."))
		return
	if not any(donation.has_value_changed(fieldname) for fieldname in FULFILLMENT_FIELDS):
		return
	if donation.flags.get("tribute_fulfillment_capability") is not _FULFILLMENT_WRITE_CAPABILITY:
		frappe.throw(_("Tribute fulfillment state can only be changed through the fulfillment action."))


def _validate_fulfillment_audit(donation) -> None:
	status = cstr(donation.tribute_fulfillment_status).strip() or "Not Requested"
	if status not in FULFILLMENT_STATUSES:
		frappe.throw(_("Invalid tribute fulfillment status."))
	if status in TERMINAL_FULFILLMENT_STATUSES:
		if not donation.tribute_fulfilled_on or not donation.tribute_fulfilled_by:
			frappe.throw(_("Terminal tribute fulfillment requires date and user audit fields."))
	elif any(
		(donation.tribute_fulfilled_on, donation.tribute_fulfilled_by, donation.tribute_fulfillment_note)
	):
		frappe.throw(_("Open tribute fulfillment cannot carry terminal audit fields."))


def _bounded_text(value: str | None, limit: int, label: str) -> str:
	value = cstr(value).strip()
	if len(value) > limit:
		frappe.throw(_("{0} cannot exceed {1} characters.").format(label, limit))
	return value
