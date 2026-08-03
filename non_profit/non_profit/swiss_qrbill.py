"""Minimal Swiss QR-bill generator for Donation / Sales Invoice print formats.

Dispatches to ``non_profit_qr_bill_svg_providers`` hooks first, so private
downstream apps can render richer, bank-grade slips without this public
repository importing them. The standalone fallback uses the `qrbill` PyPI
package (SIX-compliant) with creditor details from `Non Profit Settings`,
so each NGO configures their own IBAN and address.

Returns an inline error message when creditor details are not configured.
"""

from __future__ import annotations

from io import StringIO

import frappe
from frappe.utils import flt

QR_BILL_SVG_PROVIDER_HOOK = "non_profit_qr_bill_svg_providers"


def _resolve_creditor() -> tuple[str | None, dict | None]:
	settings = frappe.get_single("Non Profit Settings")
	iban = getattr(settings, "creditor_iban", None) or ""
	if not iban:
		return None, None
	creditor = {
		"name": getattr(settings, "creditor_name", None) or "",
		"line1": getattr(settings, "creditor_address_line1", None) or "",
		"line2": getattr(settings, "creditor_address_line2", None) or "",
		"country": "CH",
	}
	return iban, creditor


def swiss_qrbill_svg(doc) -> str:
	"""Jinja-safe helper: returns an SVG string for a QR-bill.

	Accepts a Donation or Sales Invoice document. Amount is pulled from
	`amount` or `grand_total`; debtor from `donor_name`/`customer_name`.
	Errors are swallowed to a visible inline message so a bad config never
	crashes the print format.

	Providers registered under ``non_profit_qr_bill_svg_providers`` are
	consulted first (private downstream apps deliver QRR-referenced slips
	there); the standalone qrbill fallback below must stay free of
	private-app imports — this repository is public.
	"""
	for method in frappe.get_hooks(QR_BILL_SVG_PROVIDER_HOOK) or []:
		try:
			if svg := frappe.get_attr(method)(doc):
				return svg
		except Exception:
			frappe.log_error(frappe.get_traceback(), "non_profit QR-bill provider failed")

	try:
		iban, creditor = _resolve_creditor()
		if not iban or not creditor:
			return '<p style="color:#b94a48;">Swiss QR-Bill: creditor IBAN not configured in Non Profit Settings.</p>'

		try:
			from qrbill import QRBill
		except ImportError:
			return (
				'<p style="color:#b94a48;">qrbill package not installed — '
				"run <code>./env/bin/pip install qrbill</code></p>"
			)

		amount_raw = doc.get("amount") or doc.get("grand_total") or 0
		amount = flt(amount_raw)
		amount_str = f"{amount:.2f}" if amount > 0 else None

		# Debtor is optional on QR-bill — we only pass it if we have a
		# complete address (postal code is mandatory in the spec). Otherwise
		# the donor fills in their details on the printed slip.
		debtor = None

		# The registered QRR lives on the document itself (gc_qr_reference,
		# written by this app's own reference registration on submit). It must
		# reach the slip: a QR-IBAN account is invalid without a QRR, and a
		# slip without the registered reference can never auto-reconcile.
		reference = (doc.get("gc_qr_reference") or "").strip() or None

		bill = QRBill(
			account=iban,
			creditor=creditor,
			amount=amount_str,
			currency="CHF",
			debtor=debtor,
			reference_number=reference,
			additional_information=doc.get("name") or "",
			language="de",
		)
		out = StringIO()
		bill.as_svg(out)
		return out.getvalue()
	except Exception as e:
		return (
			f'<p style="color:#b94a48;">Swiss QR-Bill konnte nicht erstellt werden: '
			f"{frappe.utils.escape_html(str(e))}</p>"
		)
