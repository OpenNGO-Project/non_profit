from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import nowdate, validate_email_address

from non_profit.non_profit.doctype.donor.donor import (
	find_donor_by_email,
	get_or_create_customer_for_donor,
)

try:
	from good_connector.captcha import (
		GOODVANTAGE_CAPTCHA_RESPONSE_FIELD,
		get_goodvantage_captcha_site_key,
		verify_goodvantage_captcha_response,
	)
except ImportError:
	GOODVANTAGE_CAPTCHA_RESPONSE_FIELD = "gv-captcha-response"
	get_goodvantage_captcha_site_key = None
	verify_goodvantage_captcha_response = None


no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.captcha_site_key = _captcha_site_key()

	if frappe.request and frappe.request.method == "POST":
		try:
			donation_name = _handle_submission(frappe.form_dict)
		except frappe.ValidationError as e:
			context.error = str(e)
			context.campaigns = _get_active_campaigns()
			return context
		frappe.local.flags.redirect_location = f"/donate_confirm?{donation_confirm_query(donation_name)}"
		raise frappe.Redirect

	context.campaigns = _get_active_campaigns()
	return context


def donation_confirm_query(donation_name: str) -> str:
	"""Query string for the donate_confirm page, including the per-donation key.

	The key gates the public confirmation page — Donation names are a
	sequential series, so the page is not reachable by name alone.
	"""
	params = {"donation": donation_name}
	confirmation_key = frappe.db.get_value("Donation", donation_name, "confirmation_key")
	if confirmation_key:
		params["key"] = confirmation_key
	return urlencode(params)


def _get_active_campaigns():
	return frappe.get_all(
		"Donation Campaign",
		filters={"status": "Active"},
		fields=["name", "campaign_name"],
		order_by="campaign_name",
	)


@rate_limit(limit=20, seconds=60 * 60)
def _handle_submission(form):
	_verify_captcha(form)
	donor_name = (form.get("donor_name") or "").strip()
	email = (form.get("email") or "").strip().lower()
	amount_raw = form.get("amount")
	frequency = form.get("frequency") or "one_off"
	campaign = form.get("campaign") or None
	consent = form.get("consent")

	if not donor_name or not email or not amount_raw:
		frappe.throw(_("Please fill in name, email and amount"))
	validate_email_address(email, throw=True)
	if str(consent or "").lower() not in {"1", "true", "yes", "on"}:
		frappe.throw(_("Please agree to the storage of your data."))

	try:
		amount = float(amount_raw)
	except TypeError, ValueError:
		frappe.throw(_("Invalid amount"))

	if amount <= 0:
		frappe.throw(_("Amount must be positive"))
	if frequency not in {"one_off", "Monthly", "Quarterly", "Yearly"}:
		frappe.throw(_("Invalid donation frequency"))
	if campaign and not frappe.db.exists("Donation Campaign", {"name": campaign, "status": "Active"}):
		frappe.throw(_("Selected campaign is not available."))

	settings = frappe.get_single("Non Profit Settings")

	donor_type = settings.default_donor_type or "Individual"
	if not frappe.db.exists("Donor Type", donor_type):
		dt = frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type})
		dt.flags.ignore_permissions = True
		dt.insert()

	donor_record = find_donor_by_email(email)
	if not donor_record:
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": donor_name,
				"donor_type": donor_type,
			}
		)
		donor.flags.ignore_permissions = True
		donor.insert()
		donor_record = donor.name
	else:
		donor = frappe.get_doc("Donor", donor_record)
		if donor.donor_name != donor_name:
			# Never let unauthenticated input rewrite an existing master
			# record (the old rename let anyone knowing a donor's email
			# deface their record and receipts). Leave a note for staff.
			donor.add_comment(
				"Comment",
				_("Public donation form submitted a different donor name: {0}").format(donor_name),
			)
	get_or_create_customer_for_donor(donor, email=email)

	company = settings.donation_company or frappe.db.get_default("company")
	if not company:
		company = frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw(_("No Company configured on Non Profit Settings"))

	if frequency == "one_off":
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": donor_record,
				"donor_name": donor_name,
				"email": email,
				"company": company,
				"date": nowdate(),
				"amount": amount,
				"campaign": campaign,
			}
		)
		donation.flags.ignore_permissions = True
		donation.insert()
		donation.submit()
		return donation.name

	rec = frappe.get_doc(
		{
			"doctype": "Recurring Donation",
			"donor": donor_record,
			"company": company,
			"amount": amount,
			"frequency": frequency,
			"start_date": nowdate(),
			"next_date": nowdate(),
			"status": "Active",
			"campaign": campaign,
		}
	)
	rec.flags.ignore_permissions = True
	rec.insert()
	donation = rec.create_donation(mark_paid=False)
	rec.advance_next_date()
	rec.save(ignore_permissions=True)
	return donation.name


def _captcha_site_key() -> str:
	if not get_goodvantage_captcha_site_key:
		return ""
	try:
		return get_goodvantage_captcha_site_key()
	except Exception:
		return ""


def _verify_captcha(form) -> None:
	if frappe.session.user != "Guest":
		return
	if not _captcha_site_key():
		return
	if not verify_goodvantage_captcha_response:
		frappe.throw(_("CAPTCHA is not configured. Please contact support."))
	response = (form.get(GOODVANTAGE_CAPTCHA_RESPONSE_FIELD) or form.get("captcha_response") or "").strip()
	if not verify_goodvantage_captcha_response(response):
		frappe.throw(_("CAPTCHA failed. Please try again."))
