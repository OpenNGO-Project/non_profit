# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_link_to_form, getdate, now_datetime

from non_profit.non_profit.doctype.donor.donor import (
	find_donor_by_email,
	get_donor_email,
	get_or_create_customer_for_donor,
)

SENSITIVE_DONOR_NOTE_KEYS = ("pan", "tax_id", "tax id", "tax-number", "tax_number")


class Donation(Document):
	def before_insert(self):
		# Random key gating the public donate_confirm page: Donation names are
		# a sequential series, so the page must not be reachable by name alone.
		if not self.get("confirmation_key"):
			self.confirmation_key = frappe.generate_hash(length=32)

	def validate(self):
		if self.donor:
			self.email = get_donor_email(self.donor) or self.email
		if not self.donor or not frappe.db.exists("Donor", self.donor):
			# for web forms
			user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
			if user_type == "Website User":
				self.create_donor_for_website_user()
			else:
				frappe.throw(_("Please select a Donor"))
		self._validate_major_gift_donor()

	def _validate_major_gift_donor(self):
		# A linked Major Gift must belong to the same Donor as this Donation.
		if not self.major_gift or not self.donor:
			return
		gift_donor = frappe.db.get_value("Major Gift", self.major_gift, "donor")
		if gift_donor and gift_donor != self.donor:
			frappe.throw(_("Major Gift {0} belongs to a different donor.").format(self.major_gift))

	def create_donor_for_website_user(self):
		donor_name = find_donor_by_email(frappe.session.user)

		if not donor_name:
			user = frappe.get_doc("User", frappe.session.user)
			donor = frappe.get_doc(
				dict(
					doctype="Donor",
					donor_type=self.get("donor_type"),
					donor_name=user.get_fullname(),
				)
			).insert(ignore_permissions=True)
			get_or_create_customer_for_donor(donor, email=frappe.session.user)
			donor_name = donor.name

		if self.get("__islocal"):
			self.donor = donor_name

	def on_payment_authorized(self, *args, **kwargs):
		self.db_set("paid", 1)
		self.load_from_db()
		try:
			self.create_payment_entry()
		except Exception:
			self.db_set("paid", 0)
			frappe.log_error(
				title=f"Donation payment entry failed for {self.name}",
				message=frappe.get_traceback(),
			)
			raise
		try:
			self._send_thank_you()
		except Exception:
			frappe.log_error(title=f"Thank-you dispatch failed for {self.name}")
		try:
			from non_profit.non_profit.major_gifts import on_donation_change

			on_donation_change(self)
		except Exception:
			frappe.log_error(title=f"Donor roll-up refresh failed for {self.name}")

	def before_print(self, settings=None):
		from non_profit.non_profit.swiss_qrbill import swiss_qrbill_svg

		self.qr_bill_svg = swiss_qrbill_svg(self)

	@frappe.whitelist()
	def send_thank_you(self) -> bool:
		# run_doc_method only enforces read permission; sending email and
		# stamping audit fields is a write-level action.
		self.check_permission("write")
		return self._send_thank_you()

	def _send_thank_you(self) -> bool:
		settings = frappe.get_single("Non Profit Settings")
		template_name = settings.default_thank_you_template
		if not template_name or not self.email:
			return False
		template = frappe.get_doc("Email Template", template_name)
		context = {"doc": self.as_dict()}
		subject = frappe.render_template(template.subject, context)
		body = template.response or template.response_html or ""
		message = frappe.render_template(body, context)
		# Queue the email; the scheduler sends it. Avoid now=True since that
		# runs SMTP synchronously on commit and can break the payment flow.
		email_queue = frappe.sendmail(
			recipients=[self.email],
			subject=subject,
			message=message,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)
		self._mark_thank_you_sent(email_queue=email_queue)
		return True

	@frappe.whitelist()
	def mark_thank_you_sent(self) -> bool:
		self.check_permission("write")
		self._mark_thank_you_sent()
		return True

	def _mark_thank_you_sent(self, email_queue: object | None = None) -> None:
		updates = {}
		if self.meta.has_field("thank_you_sent"):
			updates["thank_you_sent"] = 1
		if self.meta.has_field("thank_you_sent_on"):
			updates["thank_you_sent_on"] = now_datetime()
		if self.meta.has_field("thank_you_email_queue") and getattr(email_queue, "name", None):
			updates["thank_you_email_queue"] = email_queue.name
		if self.meta.has_field("thank_you_sent_by"):
			updates["thank_you_sent_by"] = frappe.session.user
		if updates:
			self.db_set(updates, update_modified=False)

	def create_payment_entry(self, date=None):
		settings = frappe.get_doc("Non Profit Settings")
		if not settings.automate_donation_payment_entries:
			return

		if not settings.donation_payment_account:
			frappe.throw(
				_("You need to set <b>Payment Account</b> for Donation in {0}").format(
					get_link_to_form("Non Profit Settings", "Non Profit Settings")
				)
			)

		from non_profit.non_profit.custom_doctype.payment_entry import (
			get_donation_payment_entry,
		)

		previous_ignore_account_permission = getattr(frappe.flags, "ignore_account_permission", False)
		frappe.flags.ignore_account_permission = True
		try:
			pe = get_donation_payment_entry(dt=self.doctype, dn=self.name)
		finally:
			frappe.flags.ignore_account_permission = previous_ignore_account_permission
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


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: guest-whitelisted-method
def mock_pay(donation: str) -> dict[str, str]:
	"""Development-only mock payment endpoint."""
	if not mock_donation_payments_enabled():
		frappe.throw(_("Mock donation payments are disabled."), frappe.PermissionError)
	return authorize_mock_donation_payment(donation)


def mock_donation_payments_enabled() -> bool:
	"""Return whether public mock donation payments may run on this site."""
	return bool(
		cint(frappe.conf.get("developer_mode")) and cint(frappe.conf.get("enable_non_profit_mock_payments"))
	)


def authorize_mock_donation_payment(donation: str) -> dict[str, str]:
	"""Mark a Donation paid through the explicitly enabled local mock gateway."""
	doc = frappe.get_doc("Donation", donation)
	if doc.paid:
		return {"status": "already_paid", "donation": doc.name}
	doc.flags.ignore_permissions = True
	doc.run_method("on_payment_authorized")
	return {"status": "success", "donation": doc.name}


def create_gateway_donation(donor, payment):
	if not frappe.db.exists("Mode of Payment", payment.method):
		create_mode_of_payment(payment.method)

	company = get_company_for_donations()
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"company": company,
			"donor": donor.name,
			"donor_name": donor.donor_name,
			"email": get_donor_email(donor),
			"date": getdate(),
			"amount": flt(payment.amount),
			"mode_of_payment": payment.method,
			"payment_id": payment.id,
		}
	).insert(ignore_mandatory=True)

	donation.submit()
	return donation


def get_donor(email):
	donor = find_donor_by_email(email)
	return frappe.get_doc("Donor", donor) if donor else None


@frappe.whitelist()
def create_donor(payment: dict) -> str:
	donor_details = frappe._dict(payment)
	frappe.only_for(("Non Profit Manager", "Non Profit Member", "System Manager"))
	donor_type = frappe.db.get_single_value("Non Profit Settings", "default_donor_type")

	donor = frappe.new_doc("Donor")
	donor.update(
		{
			"donor_name": donor_details.email,
			"donor_type": donor_type,
			"contact": donor_details.contact,
		}
	)

	if donor_details.get("notes"):
		donor = get_additional_notes(donor, donor_details)

	donor.insert(ignore_mandatory=True)
	get_or_create_customer_for_donor(donor, email=donor_details.email)
	return donor.name


def get_company_for_donations():
	company = frappe.db.get_single_value("Non Profit Settings", "donation_company")
	if not company:
		from non_profit.non_profit.utils import get_company

		company = get_company()
	return company


def get_additional_notes(donor, donor_details):
	if isinstance(donor_details.notes, dict):
		note_lines = []
		for k, v in donor_details.notes.items():
			# extract donor name from notes
			if "name" in k.lower():
				donor.update({"donor_name": donor_details.notes.get(k)})
			if _is_sensitive_note_key(k):
				continue
			note_lines.append("{}: {}".format(k, v))

		if note_lines:
			donor.add_comment("Comment", "\n".join(note_lines))

	elif isinstance(donor_details.notes, str):
		notes = _safe_note_text(donor_details.notes)
		if notes:
			donor.add_comment("Comment", notes)

	return donor


def _is_sensitive_note_key(key: object) -> bool:
	key = str(key or "").strip().lower()
	return any(part in key for part in SENSITIVE_DONOR_NOTE_KEYS)


def _safe_note_text(notes: str) -> str:
	safe_lines = []
	for line in str(notes or "").splitlines():
		key = line.split(":", 1)[0]
		if _is_sensitive_note_key(key):
			continue
		safe_lines.append(line)
	return "\n".join(safe_lines).strip()


def create_mode_of_payment(method):
	frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": method}).insert(ignore_mandatory=True)
