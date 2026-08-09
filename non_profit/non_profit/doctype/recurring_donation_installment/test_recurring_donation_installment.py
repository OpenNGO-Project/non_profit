from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.doctype.recurring_donation_installment.recurring_donation_installment import (
	REVERSAL_EVIDENCE_FIELDS,
	RecurringDonationInstallment,
)


class TestRecurringDonationInstallmentEvidence(UnitTestCase):
	def test_blank_zero_amount_is_not_reversal_evidence(self) -> None:
		self._installment(reversal_amount=0)._validate_reversal_evidence()

	def test_first_complete_reversal_can_replace_default_zero(self) -> None:
		before = self._installment(reversal_amount=0)
		installment = self._installment(**self._complete_evidence())
		with (
			patch.object(installment, "get_doc_before_save", return_value=before),
			patch.object(
				installment,
				"has_value_changed",
				side_effect=lambda fieldname: fieldname in REVERSAL_EVIDENCE_FIELDS,
			),
		):
			installment._validate_immutable_evidence()
			installment._validate_reversal_evidence()

	def test_partial_and_nonpositive_reversal_evidence_is_rejected(self) -> None:
		cases = {
			"partial": {
				"reversal_source": "Accounting",
				"reversal_kind": "Payment Entry Cancellation",
				"reversal_amount": 0,
			},
			"positive amount only": {"reversal_amount": 25},
			"zero complete fields": self._complete_evidence(reversal_amount=0),
			"negative complete fields": self._complete_evidence(reversal_amount=-25),
			"non-finite complete fields": self._complete_evidence(reversal_amount=float("inf")),
		}
		for label, values in cases.items():
			with (
				self.subTest(label=label),
				self.assertRaisesRegex(frappe.ValidationError, "reversal evidence must be complete"),
			):
				self._installment(**values)._validate_reversal_evidence()

	def test_real_reversal_evidence_is_immutable(self) -> None:
		changes = {
			"reversal_source": "Provider",
			"reversal_kind": "Full Refund",
			"reversal_reference": "PE-CHANGED",
			"reversal_date": "2026-08-10",
			"reversal_amount": 30,
			"reversal_recorded_on": "2026-08-09 11:00:00",
		}
		for changed_field, changed_value in changes.items():
			before = self._installment(**self._complete_evidence())
			installment = self._installment(**self._complete_evidence(**{changed_field: changed_value}))
			with (
				self.subTest(fieldname=changed_field),
				patch.object(installment, "get_doc_before_save", return_value=before),
				patch.object(
					installment,
					"has_value_changed",
					side_effect=lambda fieldname, target=changed_field: fieldname == target,
				),
				self.assertRaisesRegex(frappe.ValidationError, "accounting evidence cannot be changed"),
			):
				installment._validate_immutable_evidence()

	@staticmethod
	def _installment(**values) -> RecurringDonationInstallment:
		return RecurringDonationInstallment(
			{
				"doctype": "Recurring Donation Installment",
				"name": "RDI-TEST",
				"reversal_source": "",
				"reversal_kind": "",
				"reversal_amount": 0,
				**values,
			}
		)

	@staticmethod
	def _complete_evidence(**values) -> dict:
		return {
			"reversal_source": "Accounting",
			"reversal_kind": "Payment Entry Cancellation",
			"reversal_reference": "PE-TEST",
			"reversal_date": "2026-08-09",
			"reversal_amount": 25,
			"reversal_recorded_on": "2026-08-09 10:00:00",
			**values,
		}
