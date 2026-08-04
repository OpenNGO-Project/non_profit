"""Idempotent fundraising fixtures: Print Format, Email Template, Settings defaults.

Runs on `after_migrate` so a fresh bench migrate gives a working donation flow
without manual setup.
"""

from hashlib import sha256

import frappe

DONATION_TAX_RECEIPT_PRINT_FORMAT = "Spendenbescheinigung"

# German Spendenbescheinigung for `Donation Tax Receipt` (the single Bescheinigung
# since non_profit 16.10.0). The layout, the German field wording and the
# "Einzelspenden" table are carried over from the retired `Donation Receipt DE`
# format; the German income-tax paragraphs (§ 10b EStG / § 5 KStG / § 9 GewStG)
# are deliberately NOT carried over — this receipt is Swiss and CHF-only, and the
# app has always rejected German-law wording on the Swiss send path.
# The header stays address-free: donor address and issuer identity come from the
# Letter Head, exactly like the legacy format.
DONATION_TAX_RECEIPT_DE_HTML = """
<div style="font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #222;">
    <div style="text-align: right; margin-bottom: 1em;">
        <strong>Spendenbescheinigung</strong><br>
        Nr.: {{ doc.name }}
    </div>
    <h2 style="margin: 1em 0 0.3em 0;">Bestätigung über Geldzuwendungen</h2>
    <p style="font-style: italic; margin: 0 0 1.5em 0; font-size: 9pt;">Jahresbescheinigung über die im Steuerjahr {{ doc.tax_year }} geleisteten Zuwendungen</p>

    <table style="width: 100%; margin-bottom: 1.5em;">
        <tr>
			<td style="width: 35%; vertical-align: top;"><strong>Name des Zuwendenden:</strong></td>
			<td>{{ doc.donor_name | e }}</td>
        </tr>
    </table>

    <table style="width: 100%; margin-bottom: 1.5em;">
        <tr>
            <td style="width: 35%;"><strong>Betrag der Zuwendung (in Ziffern):</strong></td>
            <td><strong>{{ frappe.utils.fmt_money(doc.total_amount, currency=doc.currency) }}</strong></td>
        </tr>
        <tr>
            <td><strong>Tag der Zuwendung:</strong></td>
            <td>Steuerjahr {{ doc.tax_year }} (01.01.{{ doc.tax_year }} bis 31.12.{{ doc.tax_year }})</td>
        </tr>
    </table>

    <h3 style="margin-top: 1.5em; margin-bottom: 0.5em;">Einzelspenden</h3>
    <table style="width: 100%; border-collapse: collapse;">
        <thead>
            <tr style="background: #f2f2f2;">
                <th style="text-align: left; border: 1px solid #ccc; padding: 4px 8px;">Datum</th>
                <th style="text-align: left; border: 1px solid #ccc; padding: 4px 8px;">Referenz</th>
                <th style="text-align: right; border: 1px solid #ccc; padding: 4px 8px;">Betrag</th>
            </tr>
        </thead>
        <tbody>
            {% for row in frappe.utils.parse_json(doc.donation_details) or [] %}
            <tr>
                <td style="border: 1px solid #ccc; padding: 4px 8px;">{{ frappe.utils.format_date(row.date, "dd.MM.yyyy") }}</td>
                <td style="border: 1px solid #ccc; padding: 4px 8px;">{{ row.donation }}</td>
                <td style="text-align: right; border: 1px solid #ccc; padding: 4px 8px;">{{ frappe.utils.fmt_money(row.amount, currency=doc.currency) }}</td>
            </tr>
            {% endfor %}
            <tr style="font-weight: bold; background: #fafafa;">
                <td colspan="2" style="border: 1px solid #ccc; padding: 4px 8px;">Gesamt</td>
                <td style="text-align: right; border: 1px solid #ccc; padding: 4px 8px;">{{ frappe.utils.fmt_money(doc.total_amount, currency=doc.currency) }}</td>
            </tr>
        </tbody>
    </table>

    <p style="margin-top: 2em; font-size: 10pt;">Es handelt sich nicht um den Verzicht auf Erstattung von Aufwendungen.</p>

    <p style="margin-top: 1em; font-size: 10pt;">Wir bestätigen, dass die aufgeführten Zuwendungen eingegangen sind und ausschliesslich zur Förderung der steuerbefreiten gemeinnützigen Zwecke unserer Organisation verwendet werden. Diese Bescheinigung dient als Nachweis für Ihre Steuererklärung.</p>

    {% if doc.remarks %}<p style="margin-top: 1em; font-size: 10pt;">{{ doc.remarks }}</p>{% endif %}

    <div style="margin-top: 3em;">
        <table style="width: 100%;">
            <tr>
                <td style="width: 50%;"><strong>Ort, Datum</strong><br>
                    {{ frappe.utils.format_date(doc.issued_on or doc.creation, "dd.MM.yyyy") }}</td>
                <td style="text-align: right;"><strong>Unterschrift des Zuwendungsempfängers</strong><br><br>______________________________</td>
            </tr>
        </table>
    </div>
</div>
"""

# Keep hashes of every previously shipped body. Matching content is app-managed
# and may be upgraded; any other body belongs to the operator and is preserved.
DONATION_TAX_RECEIPT_DE_MANAGED_HASHES = frozenset(
	{
		"36fdea4641a95c1ba07c644dbb5c16a2eab35b0fd3340dfcd8a9f736ee78740f",
		"9396bff3637c5df634b3933967691a391dcc2748efd2159c8b0c63c76695cc02",
	}
)


THANK_YOU_EMAIL_HTML = """<p>Liebe/r {{ doc.donor_name | e }},</p>

<p>herzlichen Dank für Ihre großzügige Spende in Höhe von <strong>{{ frappe.utils.fmt_money(doc.amount, currency="EUR") }}</strong>!</p>

<p>Mit Ihrer Unterstützung helfen Sie uns, unsere Arbeit fortzuführen. Ihr Beitrag macht einen echten Unterschied.</p>

{% if doc.campaign %}
<p>Ihre Spende wurde der Kampagne <em>{{ doc.campaign }}</em> zugeordnet.</p>
{% endif %}

<p>Eine Zuwendungsbestätigung für das Finanzjahr senden wir Ihnen zu gegebener Zeit zu.</p>

<p>Mit herzlichen Grüßen,<br>
Ihr Team</p>"""


def ensure_fundraising_fixtures():
	from non_profit.non_profit.erpnext_loyalty import disable_test_loyalty_auto_opt_in
	from non_profit.non_profit.major_gifts import ensure_major_gift_workflow
	from non_profit.setup import ensure_non_profit_desk_roles, make_custom_fields

	make_custom_fields()
	disable_test_loyalty_auto_opt_in()
	ensure_non_profit_desk_roles()
	ensure_tax_receipt_print_format()
	ensure_swiss_qrbill_print_format()
	ensure_email_template()
	ensure_settings_defaults()
	ensure_major_gift_workflow()
	ensure_good_connector_bank_integration()


def ensure_good_connector_bank_integration() -> None:
	from non_profit.non_profit.integration_hooks import BANK_INTEGRATION_SETUP

	for dotted_path in frappe.get_hooks(BANK_INTEGRATION_SETUP) or []:
		frappe.get_attr(dotted_path)()
	from non_profit.non_profit.bank_integration import backfill_donation_qr_references

	backfill_donation_qr_references()


DONATION_SLIP_CH_HTML = """
<style>
@page { size: A4; margin: 0; }
.donation-slip-body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 10pt; margin: 16mm 17mm 18mm; }
.donation-slip-qr-page { box-sizing: border-box; font-family: 'Helvetica Neue', Arial, sans-serif; min-height: 297mm; page-break-before: always; display: flex; flex-direction: column; justify-content: flex-end; }
.donation-slip-qr-note { color: #666; font-size: 9pt; margin: 0 17mm 6mm; }
.donation-slip-qr { border-top: 1px dashed #999; padding-top: 5mm; width: 210mm; }
.donation-slip-qr svg { display: block; height: 105mm; width: 210mm; }
</style>
<div class="donation-slip-body">
	<div style="margin-bottom: 1em;">
		<h2 style="margin: 0 0 0.3em 0;">Spendenbeleg</h2>
		<p style="margin: 0; color: #666;">
			Referenz: <strong>{{ doc.name }}</strong> &nbsp;·&nbsp;
			Datum: {{ frappe.utils.format_date(doc.date, "dd.MM.yyyy") }}
		</p>
	</div>

	<table style="width: 100%; margin-bottom: 1em; border-collapse: collapse;">
		<tr>
			<td style="width: 35%; padding: 4px 0;"><strong>Spender:in</strong></td>
			<td>{{ doc.donor_name | e }}{% if doc.email %}<br>{{ doc.email | e }}{% endif %}</td>
		</tr>
		<tr>
			<td style="padding: 4px 0;"><strong>Betrag</strong></td>
			<td><strong>CHF {{ "%.2f"|format(doc.amount or 0) }}</strong></td>
		</tr>
		{% if doc.campaign %}
		<tr>
			<td style="padding: 4px 0;"><strong>Kampagne</strong></td>
			<td>{{ doc.campaign }}</td>
		</tr>
		{% endif %}
	</table>
</div>
{% if doc.qr_bill_svg %}
<div class="donation-slip-qr-page">
	<p class="donation-slip-qr-note">
		Schweizer QR-Rechnung &mdash; scannen Sie den Code mit TWINT oder Ihrer E-Banking-App:
	</p>
	<div class="donation-slip-qr donation-slip-qr-final-page-slip">{{ doc.qr_bill_svg | safe }}</div>
</div>
{% endif %}
"""

DONATION_SLIP_CH_MANAGED_HASHES = frozenset(
	{
		"55df655758ecbdd705476175b4f13e628f106fc4e6268c46b0c374ce057b7d7c",
		"930d2ea12fc6daae856332792577551e90089fa07a187556509cbfc99343f789",
	}
)


def ensure_swiss_qrbill_print_format():
	ensure_managed_print_format(
		name="Donation Slip CH",
		doc_type="Donation",
		html=DONATION_SLIP_CH_HTML,
		managed_hashes=DONATION_SLIP_CH_MANAGED_HASHES,
	)


def ensure_tax_receipt_print_format():
	ensure_managed_print_format(
		name=DONATION_TAX_RECEIPT_PRINT_FORMAT,
		doc_type="Donation Tax Receipt",
		html=DONATION_TAX_RECEIPT_DE_HTML,
		managed_hashes=DONATION_TAX_RECEIPT_DE_MANAGED_HASHES,
	)


def ensure_managed_print_format(*, name: str, doc_type: str, html: str, managed_hashes: frozenset[str]):
	if frappe.db.exists("Print Format", name):
		pf = frappe.get_doc("Print Format", name)
		if pf.html == html:
			return
		if _html_hash(pf.html) not in managed_hashes:
			return
		pf.html = html
		pf.flags.ignore_permissions = True
		pf.save()
		return
	frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": name,
			"doc_type": doc_type,
			"module": "Non Profit",
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": html,
			"disabled": 0,
		}
	).insert(ignore_permissions=True)


def _html_hash(html: str | None) -> str:
	return sha256((html or "").encode()).hexdigest()


def ensure_email_template():
	# Create-if-missing only: operators own the template content after the
	# first install, and a migrate must not silently revert their edits
	# (bench pattern: seeded Email Templates are never overwritten).
	name = "Donation Thank You DE"
	if frappe.db.exists("Email Template", name):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": name,
			"subject": "Herzlichen Dank für Ihre Spende",
			"response": THANK_YOU_EMAIL_HTML,
			"use_html": 1,
		}
	).insert(ignore_permissions=True)


def ensure_settings_defaults():
	settings = frappe.get_single("Non Profit Settings")
	changed = False

	# Best-effort fill of mandatory fields so that save() doesn't abort migrate.
	# A fresh non_profit install leaves these blank; we seed them so the donation
	# flow works out of the box.
	if not settings.company:
		company = frappe.db.get_value("Company", {}, "name")
		if company:
			settings.company = company
			changed = True
	if not settings.donation_company:
		company = settings.company or frappe.db.get_value("Company", {}, "name")
		if company:
			settings.donation_company = company
			changed = True
	if not settings.default_donor_type:
		if not frappe.db.exists("Donor Type", "Individual"):
			frappe.get_doc({"doctype": "Donor Type", "donor_type": "Individual"}).insert(
				ignore_permissions=True
			)
		settings.default_donor_type = "Individual"
		changed = True
	if not settings.creation_user:
		settings.creation_user = "Administrator"
		changed = True

	if not settings.default_thank_you_template and frappe.db.exists(
		"Email Template", "Donation Thank You DE"
	):
		settings.default_thank_you_template = "Donation Thank You DE"
		changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		try:
			settings.save()
		except Exception:
			frappe.log_error(title="Non Profit Settings fundraising defaults save failed")
