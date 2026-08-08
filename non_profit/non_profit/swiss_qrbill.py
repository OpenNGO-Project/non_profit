"""Swiss QR-bill seam for Donation / Sales Invoice print formats.

This repository is public and must not import private apps, so it renders no
QR-bill itself: it dispatches ``non_profit_qr_bill_svg_providers`` and returns
whatever the first provider produces.

There is deliberately no standalone fallback. The one that used to live here
could forward a stored QRR without first proving that the creditor account was a
QR-IBAN, used a separate validation path, and hardcoded German for every
recipient.

Returns "" when no provider answers, which prints the document without a slip.
"""

from __future__ import annotations

import frappe

QR_BILL_SVG_PROVIDER_HOOK = "non_profit_qr_bill_svg_providers"


def swiss_qrbill_svg(doc) -> str:
	"""Jinja-safe helper: the QR-bill SVG for a Donation or Sales Invoice.

	Accepts any document the registered provider understands. A provider that
	cannot render (creditor IBAN unconfigured, address incomplete) returns "".
	Retryable database errors propagate so the complete transaction can retry.
	"""
	for method in frappe.get_hooks(QR_BILL_SVG_PROVIDER_HOOK) or []:
		try:
			if svg := frappe.get_attr(method)(doc):
				return svg
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):  # fmt: skip
			raise
		except Exception:
			frappe.log_error(title="non_profit QR-bill provider failed", message=frappe.get_traceback())
	return ""
