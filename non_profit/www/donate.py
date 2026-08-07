from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, cstr, nowdate, validate_email_address

from non_profit.non_profit.campaign_gate import campaign_matches_company
from non_profit.non_profit.doctype.donor.donor import (
	find_donor_by_email,
	get_or_create_customer_for_donor,
)
from non_profit.non_profit.identity_lock import acquire_public_email_identity_lock
from non_profit.non_profit.integration_hooks import CAPTCHA, first_provider

DEFAULT_CAPTCHA_RESPONSE_FIELD = "gv-captcha-response"


def public_donate_pages_enabled() -> bool:
	"""Whether the generic `/donate` and `/donate_confirm` pages are served.

	Off unless the site opts in. Deployments commonly provide their own branded
	donation form or campaign page; the generic pages are an unstyled fallback
	with hard-coded EUR labels, so leaving them reachable can expose a second,
	off-brand donation surface.
	"""
	return bool(cint(frappe.conf.get("enable_non_profit_public_donate_pages")))


def require_public_donate_pages() -> None:
	"""404 the generic donation pages unless the site opted in.

	`DoesNotExistError`, not `PageDoesNotExistError`. Both render the 404 body,
	but only the former produces a real 404 *status*: `website.serve` passes the
	incoming status code into `NotFoundPage`, whose `http_status_code or 404`
	then keeps the 200 it was handed. `DoesNotExistError` instead goes through
	`handle_does_not_exist_error`. `test_donate.py` asserts the status code rather
	than the exception class because this distinction is invisible in the page
	body.
	"""
	if not public_donate_pages_enabled():
		raise frappe.DoesNotExistError


def _captcha_backend() -> dict:
	"""Captcha config from the registered provider hook; empty dict when none.

	Providers return {"response_field": str, "site_key": callable, "verify": callable}.
	"""
	provider = first_provider(CAPTCHA)
	return provider() if provider else {}


no_cache = 1


def get_context(context):
	# Before any campaign lookup or POST handling: a disabled page must not
	# accept submissions either.
	require_public_donate_pages()
	context.no_cache = 1
	context.show_sidebar = False
	context.captcha_site_key = _captcha_site_key()
	context.recurring_request_key = cstr(frappe.form_dict.get("request_key")).strip() or frappe.generate_hash(
		length=32
	)

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
	company = _resolve_donation_company()
	if not company:
		return []
	cost_centers = frappe.get_all(
		"Cost Center",
		filters={"company": company, "is_group": 0, "disabled": 0},
		pluck="name",
		limit_page_length=0,
	)
	if not cost_centers:
		return []
	return frappe.get_all(
		"Donation Campaign",
		filters={"status": "Active", "cost_center": ["in", cost_centers]},
		fields=["name", "campaign_name"],
		order_by="campaign_name",
		limit_page_length=0,
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
	message = (form.get("message") or "").strip()[:1000]
	request_key = cstr(form.get("request_key")).strip() or None

	if not donor_name or not email or not amount_raw:
		frappe.throw(_("Please fill in name, email and amount"))
	validate_email_address(email, throw=True)
	acquire_public_email_identity_lock(email)
	if str(consent or "").lower() not in {"1", "true", "yes", "on"}:
		frappe.throw(_("Please agree to the storage of your data."))

	# Same bounds as every other public intake path (CHF 5 - 100'000);
	# the shared validator also rejects non-finite values (nan/inf) first.
	from non_profit.non_profit.utils import validate_public_donation_amount

	amount = validate_public_donation_amount(str(amount_raw))
	# Quarterly/Yearly remain available on the doctype for schedules staff
	# create by hand; the public page offers one-off and monthly.
	if frequency not in {"one_off", "Monthly"}:
		frappe.throw(_("Invalid donation frequency"))
	settings = frappe.get_single("Non Profit Settings")
	company = _resolve_donation_company(settings)
	if not company:
		frappe.throw(_("No Company configured on Non Profit Settings"))
	if campaign and not campaign_matches_company(campaign, company):
		frappe.throw(_("Selected campaign is not available for the Donation company."))

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

	# A payment integration, when one is installed, owns the whole collection
	# path: it creates the schedule with its own provider linkage and returns a
	# checkout URL. Without it this page records the gift and collects nothing —
	# which is what it did for every donation before this seam existed.
	checkout = _delegate_public_checkout(
		donor=donor_record,
		donor_name=donor_name,
		email=email,
		company=company,
		amount=amount,
		frequency=frequency,
		campaign=campaign,
		message=message,
		request_key=request_key,
	)
	if checkout:
		return checkout

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
		_add_donor_message(donation, message)
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
	_add_donor_message(donation, message)
	return donation.name


PUBLIC_CHECKOUT_PROVIDER_HOOK = "non_profit_public_donation_checkout_providers"


def _delegate_public_checkout(**values) -> str | None:
	"""Let an installed payment integration own the public donation checkout.

	This app is public and never imports a payment integration, so it cannot
	build a checkout itself. A registered provider creates the Donation (and,
	for a recurring gift, the schedule carrying its own provider linkage) and
	returns a URL to send the donor to. Returning None means no provider is
	installed and the local record-only behaviour applies.

	Provider failures are not swallowed: a donor who was told their gift was
	set up, but whose checkout never happened, is worse than an error page.
	"""
	for provider in frappe.get_hooks(PUBLIC_CHECKOUT_PROVIDER_HOOK):
		checkout_url = frappe.get_attr(provider)(**values)
		if checkout_url:
			frappe.local.flags.redirect_location = checkout_url
			raise frappe.Redirect
	return None


def _add_donor_message(donation, message: str) -> None:
	if message:
		donation.add_comment("Comment", _("Donor message: {0}").format(message))


def _resolve_donation_company(settings=None) -> str | None:
	settings_company = (
		settings.donation_company
		if settings
		else frappe.db.get_single_value("Non Profit Settings", "donation_company")
	)
	return (
		settings_company
		or frappe.db.get_default("company")
		or frappe.db.get_value("Company", {}, "name", order_by="name asc")
	)


def _captcha_site_key() -> str:
	backend = _captcha_backend()
	site_key = backend.get("site_key")
	return site_key() if site_key else ""


def _verify_captcha(form) -> None:
	if frappe.session.user != "Guest":
		return
	backend = _captcha_backend()
	if not _captcha_site_key() or not backend.get("verify"):
		frappe.throw(_("CAPTCHA is not configured. Please contact support."))
	response_field = backend.get("response_field") or DEFAULT_CAPTCHA_RESPONSE_FIELD
	response = (form.get(response_field) or form.get("captcha_response") or "").strip()
	if not backend["verify"](response):
		frappe.throw(_("CAPTCHA failed. Please try again."))
