import frappe
from frappe import _
from frappe.utils import nowdate


no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.request and frappe.request.method == "POST":
		try:
			donation_name = _handle_submission(frappe.form_dict)
		except frappe.ValidationError as e:
			context.error = str(e)
			context.campaigns = _get_active_campaigns()
			return context
		frappe.local.flags.redirect_location = f"/donate_confirm?donation={donation_name}"
		raise frappe.Redirect

	context.campaigns = _get_active_campaigns()
	return context


def _get_active_campaigns():
	return frappe.get_all(
		"Donation Campaign",
		filters={"status": "Active"},
		fields=["name", "campaign_name"],
		order_by="campaign_name",
	)


def _handle_submission(form):
	donor_name = (form.get("donor_name") or "").strip()
	email = (form.get("email") or "").strip().lower()
	amount_raw = form.get("amount")
	frequency = form.get("frequency") or "one_off"
	campaign = form.get("campaign") or None

	if not donor_name or not email or not amount_raw:
		frappe.throw(_("Please fill in name, email and amount"))

	try:
		amount = float(amount_raw)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid amount"))

	if amount <= 0:
		frappe.throw(_("Amount must be positive"))

	settings = frappe.get_single("Non Profit Settings")

	donor_type = settings.default_donor_type or "Individual"
	if not frappe.db.exists("Donor Type", donor_type):
		dt = frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type})
		dt.flags.ignore_permissions = True
		dt.insert()

	donor_record = frappe.db.get_value("Donor", {"email": email}, "name")
	if not donor_record:
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": donor_name,
				"email": email,
				"donor_type": donor_type,
			}
		)
		donor.flags.ignore_permissions = True
		donor.insert()
		donor_record = donor.name

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
