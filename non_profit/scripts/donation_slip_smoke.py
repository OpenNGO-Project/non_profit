from __future__ import annotations

import frappe
from frappe.utils.pdf import get_pdf


def send_donation_slip_smoke(recipient: str) -> dict:
	"""Manual smoke for bench execute: send the Donation Slip CH QR PDF.

    Run with:
      bench --site <site> execute \
        non_profit.scripts.donation_slip_smoke.send_donation_slip_smoke \
        --kwargs "{'recipient': 'you@example.com'}"
    """
	if not recipient:
		frappe.throw("recipient is required")
	from non_profit.non_profit.doctype.donor.donor import (
		get_or_create_customer_for_donor,
	)
	from non_profit.non_profit.fundraising_setup import ensure_fundraising_fixtures

	ensure_fundraising_fixtures()
	_ensure_donor_type()
	donor = frappe.get_doc(
		{
			"doctype": "Donor",
			"donor_name": "QR Smoke Donor",
			"donor_type": "QR Smoke Donor",
		}
	).insert(ignore_permissions=True)
	get_or_create_customer_for_donor(donor, email=recipient)
	donor.reload()
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"company": frappe.get_cached_value("Non Profit Settings", None, "company"),
			"donor": donor.name,
			"donor_name": donor.donor_name,
			"email": recipient,
			"date": _active_fiscal_year_date(),
			"amount": 42,
			"paid": 1,
		}
	).insert(ignore_permissions=True)
	donation.submit()
	donation.before_print()
	print_format = frappe.get_doc("Print Format", "Donation Slip CH")
	pdf_html = frappe.render_template(print_format.html or "", {"doc": donation, "frappe": frappe})
	attachment = {
		"fname": f"Donation-Slip-CH-{donation.name}.pdf",
		"fcontent": get_pdf(pdf_html),
	}
	queue_doc = frappe.sendmail(
		recipients=[recipient],
		subject=f"[Smoke non_profit] Donation Slip CH {donation.name}",
		message="<p>Smoke-Test fuer den non_profit Donation Slip CH mit QR-Zahlteil.</p>",
		reference_doctype="Donation",
		reference_name=donation.name,
		attachments=[attachment],
	)
	queue_name = getattr(queue_doc, "name", None) or _latest_email_queue_for_recipient(recipient)
	if queue_name:
		frappe.get_doc("Email Queue", queue_name).send()
	# Standalone bench-execute script: persist the smoke fixture explicitly.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return {
		"donor": donor.name,
		"donation": donation.name,
		"recipient": recipient,
		"email_queue": queue_name,
	}


def _ensure_donor_type() -> None:
	if not frappe.db.exists("Donor Type", "QR Smoke Donor"):
		frappe.get_doc({"doctype": "Donor Type", "donor_type": "QR Smoke Donor"}).insert(
			ignore_permissions=True
		)


def _active_fiscal_year_date():
	fiscal_year = frappe.get_all(
		"Fiscal Year",
		filters={"disabled": 0},
		fields=["year_start_date"],
		order_by="year_start_date desc",
		limit=1,
	)
	return fiscal_year[0].year_start_date if fiscal_year else frappe.utils.getdate()


def _latest_email_queue_for_recipient(recipient: str) -> str | None:
	rows = frappe.get_all(
		"Email Queue Recipient",
		filters={"recipient": recipient},
		fields=["parent"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0].parent if rows else None
