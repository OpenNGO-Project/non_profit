# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from math import isfinite

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

_RECONCILIATION_WRITE_CAPABILITY = object()
_EVIDENCE_REMAP_CAPABILITY = object()
ACTUAL_SNAPSHOT_FIELDS = ("donation", "actual_date", "actual_amount")
REVERSAL_EVIDENCE_FIELDS = (
	"reversal_source",
	"reversal_kind",
	"reversal_reference",
	"reversal_date",
	"reversal_amount",
	"reversal_recorded_on",
)
REVERSAL_SOURCES = {
	"Payment Entry Cancellation": "Accounting",
	"Full Refund": "Provider",
	"Chargeback": "Provider",
}


class RecurringDonationInstallment(Document):
	def before_insert(self) -> None:
		self._require_reconciliation_write()

	def validate(self) -> None:
		self._require_reconciliation_write()
		self._validate_immutable_evidence()
		self._validate_reversal_evidence()

	def on_trash(self) -> None:
		self._require_reconciliation_write()

	def _require_reconciliation_write(self) -> None:
		if self.flags.get("reconciliation_write_capability") is not _RECONCILIATION_WRITE_CAPABILITY:
			frappe.throw(
				_("Recurring Donation Installments are maintained by reconciliation."),
				frappe.PermissionError,
			)

	def _validate_immutable_evidence(self) -> None:
		if self.flags.get("evidence_remap_capability") is _EVIDENCE_REMAP_CAPABILITY:
			if (
				not self.is_retired
				or any(
					_has_actual_snapshot_value(fieldname, self.get(fieldname))
					for fieldname in ACTUAL_SNAPSHOT_FIELDS
				)
				or _has_any_reversal_evidence(self)
			):
				frappe.throw(_("Only complete evidence removal from a retired installment can be remapped."))
			return
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in ACTUAL_SNAPSHOT_FIELDS:
			if _has_actual_snapshot_value(fieldname, before.get(fieldname)) and self.has_value_changed(
				fieldname
			):
				frappe.throw(_("Recurring installment accounting evidence cannot be changed."))
		if _has_real_reversal_evidence(before) and any(
			self.has_value_changed(fieldname) for fieldname in REVERSAL_EVIDENCE_FIELDS
		):
			frappe.throw(_("Recurring installment accounting evidence cannot be changed."))

	def _validate_reversal_evidence(self) -> None:
		if not _has_any_reversal_evidence(self):
			return
		if not _has_complete_reversal_evidence(self):
			frappe.throw(_("Recurring installment reversal evidence must be complete."))
		if REVERSAL_SOURCES.get(self.reversal_kind) != self.reversal_source:
			frappe.throw(_("Recurring installment reversal source and kind do not match."))


def allow_reconciliation_write(installment) -> None:
	installment.flags.reconciliation_write_capability = _RECONCILIATION_WRITE_CAPABILITY


def allow_evidence_remap(installment) -> None:
	allow_reconciliation_write(installment)
	installment.flags.evidence_remap_capability = _EVIDENCE_REMAP_CAPABILITY


def _has_actual_snapshot_value(fieldname: str, value) -> bool:
	if fieldname == "actual_amount":
		return flt(value) != 0
	return value not in (None, "")


def _has_any_reversal_evidence(installment) -> bool:
	return flt(installment.get("reversal_amount")) != 0 or any(
		installment.get(fieldname) not in (None, "")
		for fieldname in REVERSAL_EVIDENCE_FIELDS
		if fieldname != "reversal_amount"
	)


def _has_complete_reversal_evidence(installment) -> bool:
	amount = flt(installment.get("reversal_amount"))
	return (
		isfinite(amount)
		and amount > 0
		and all(
			installment.get(fieldname) not in (None, "")
			for fieldname in REVERSAL_EVIDENCE_FIELDS
			if fieldname != "reversal_amount"
		)
	)


def _has_real_reversal_evidence(installment) -> bool:
	return _has_complete_reversal_evidence(installment) and (
		REVERSAL_SOURCES.get(installment.get("reversal_kind")) == installment.get("reversal_source")
	)
