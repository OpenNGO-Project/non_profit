"""Minimal Swiss QR-bill generator for Donation / Sales Invoice print formats.

Uses the `qrbill` PyPI package (SIX-compliant). Creditor details come from
`Non Profit Settings` so each NGO configures their own IBAN and address.

Returns an inline error message when creditor details are not configured.
"""

from __future__ import annotations

from io import StringIO

import frappe
from frappe.utils import flt


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
	"""
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

		bill = QRBill(
			account=iban,
			creditor=creditor,
			amount=amount_str,
			currency="CHF",
			debtor=debtor,
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
