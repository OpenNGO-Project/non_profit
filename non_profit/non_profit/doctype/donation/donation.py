# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, getdate


class Donation(Document):
	def validate(self):
		if not self.donor or not frappe.db.exists('Donor', self.donor):
			# for web forms
			user_type = frappe.db.get_value('User', frappe.session.user, 'user_type')
			if user_type == 'Website User':
				self.create_donor_for_website_user()
			else:
				frappe.throw(_('Please select a Member'))

	def create_donor_for_website_user(self):
		donor_name = frappe.get_value('Donor', dict(email=frappe.session.user))

		if not donor_name:
			user = frappe.get_doc('User', frappe.session.user)
			donor = frappe.get_doc(dict(
				doctype='Donor',
				donor_type=self.get('donor_type'),
				email=frappe.session.user,
				member_name=user.get_fullname()
			)).insert(ignore_permissions=True)
			donor_name = donor.name

		if self.get('__islocal'):
			self.donor = donor_name

	def on_payment_authorized(self, *args, **kwargs):
		self.db_set("paid", 1)
		self.load_from_db()
		try:
			self.create_payment_entry()
		except Exception:
			frappe.log_error(title=f"Donation payment entry failed for {self.name}", message=frappe.get_traceback())
		try:
			self.send_thank_you()
		except Exception:
			frappe.log_error(title=f"Thank-you dispatch failed for {self.name}")

	def send_thank_you(self):
		settings = frappe.get_single("Non Profit Settings")
		template_name = settings.default_thank_you_template
		if not template_name or not self.email:
			return
		template = frappe.get_doc("Email Template", template_name)
		context = {"doc": self.as_dict()}
		subject = frappe.render_template(template.subject, context)
		body = template.response or template.response_html or ""
		message = frappe.render_template(body, context)
		# Queue the email; the scheduler sends it. Avoid now=True since that
		# runs SMTP synchronously on commit and can break the payment flow.
		frappe.sendmail(
			recipients=[self.email],
			subject=subject,
			message=message,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)
		if self.meta.has_field("thank_you_sent") and not self.thank_you_sent:
			self.db_set("thank_you_sent", 1, update_modified=False)

	def create_payment_entry(self, date=None):
		settings = frappe.get_doc('Non Profit Settings')
		if not settings.automate_donation_payment_entries:
			return

		if not settings.donation_payment_account:
			frappe.throw(_('You need to set <b>Payment Account</b> for Donation in {0}').format(
				get_link_to_form('Non Profit Settings', 'Non Profit Settings')))

		from non_profit.non_profit.custom_doctype.payment_entry import get_donation_payment_entry

		previous_ignore_account_permission = getattr(frappe.flags, "ignore_account_permission", False)
		frappe.flags.ignore_account_permission = True
		try:
			pe = get_donation_payment_entry(dt=self.doctype, dn=self.name)
		finally:
			frappe.flags.ignore_account_permission = previous_ignore_account_permission
		if _account_belongs_to_company(settings.donation_debit_account, self.company):
			pe.paid_from = settings.donation_debit_account
		if _account_belongs_to_company(settings.donation_payment_account, self.company):
			pe.paid_to = settings.donation_payment_account
		pe.posting_date = date or getdate()
		pe.reference_no = self.name
		pe.reference_date = date or getdate()
		pe.flags.ignore_mandatory = True
		pe.insert()
		pe.submit()

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
		)


def _account_belongs_to_company(account: str | None, company: str | None) -> bool:
	if not account or not company:
		return False
	return frappe.db.get_value("Account", account, "company") == company


@frappe.whitelist(allow_guest=True)
def mock_pay(donation):
	"""Mock payment gateway endpoint. Marks the donation as paid and fires thank-you.

	This stands in for Payrexx / Stripe / etc. during development and for the
	pitch demo. Swapping in a real gateway means replacing this function body
	with a webhook handler that verifies signatures before flipping `paid`.
	"""
	doc = frappe.get_doc("Donation", donation)
	if doc.paid:
		return {"status": "already_paid", "donation": doc.name}
	doc.flags.ignore_permissions = True
	doc.run_method("on_payment_authorized")
	frappe.db.commit()
	return {"status": "success", "donation": doc.name}


def create_gateway_donation(donor, payment):
	if not frappe.db.exists('Mode of Payment', payment.method):
		create_mode_of_payment(payment.method)

	company = get_company_for_donations()
	donation = frappe.get_doc({
		'doctype': 'Donation',
		'company': company,
		'donor': donor.name,
		'donor_name': donor.donor_name,
		'email': donor.email,
		'date': getdate(),
		'amount': flt(payment.amount),
		'mode_of_payment': payment.method,
		'payment_id': payment.id
	}).insert(ignore_mandatory=True)

	donation.submit()
	return donation


def get_donor(email):
	donors = frappe.get_all('Donor',
		filters={'email': email},
		order_by='creation desc')

	try:
		return frappe.get_doc('Donor', donors[0]['name'])
	except Exception:
		return None


@frappe.whitelist()
def create_donor(payment):
	donor_details = frappe._dict(payment)
	donor_type = frappe.db.get_single_value('Non Profit Settings', 'default_donor_type')

	donor = frappe.new_doc('Donor')
	donor.update({
		'donor_name': donor_details.email,
		'donor_type': donor_type,
		'email': donor_details.email,
		'contact': donor_details.contact
	})

	if donor_details.get('notes'):
		donor = get_additional_notes(donor, donor_details)

	donor.insert(ignore_mandatory=True)
	return donor


def get_company_for_donations():
	company = frappe.db.get_single_value('Non Profit Settings', 'donation_company')
	if not company:
		from non_profit.non_profit.utils import get_company
		company = get_company()
	return company


def get_additional_notes(donor, donor_details):
	if isinstance(donor_details.notes, dict):
		for k, v in donor_details.notes.items():
			notes = '\n'.join('{}: {}'.format(k, v))

			# extract donor name from notes
			if 'name' in k.lower():
				donor.update({
					'donor_name': donor_details.notes.get(k)
				})

			# extract pan from notes
			if 'pan' in k.lower():
				donor.update({
					'pan_number': donor_details.notes.get(k)
				})

		donor.add_comment('Comment', notes)

	elif isinstance(donor_details.notes, str):
		donor.add_comment('Comment', donor_details.notes)

	return donor


def create_mode_of_payment(method):
	frappe.get_doc({
		'doctype': 'Mode of Payment',
		'mode_of_payment': method
	}).insert(ignore_mandatory=True)
