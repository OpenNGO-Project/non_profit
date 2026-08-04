# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from math import isfinite

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_link_to_form, getdate, now_datetime

from non_profit.non_profit.doctype.donor.donor import (
	find_donor_by_email,
	get_donor_email,
	get_or_create_customer_for_donor,
)
from non_profit.non_profit.mailer import send_referenced_email


class Donation(Document):
	def before_insert(self):
		# Random key gating the public donate_confirm page: Donation names are
		# a sequential series, so the page must not be reachable by name alone.
		if not self.get("confirmation_key"):
			self.confirmation_key = frappe.generate_hash(length=32)

	def validate(self):
		self._validate_amount()
		if self.meta.has_field("grand_total"):
			# Mirrors Sales Invoice semantics: ERPNext's generic Payment Entry
			# reference-details fallback computes Donation outstanding amounts
			# as grand_total - advance_paid under any override_doctype_class
			# winner. advance_paid is maintained by sync_donation_paid_state.
			self.grand_total = self.amount
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

	def on_submit(self):
		# Keep the advance_paid mirror correct before any Payment Entry is
		# created against this Donation. The paid flag is deliberately not
		# touched here: Donations marked paid manually (without a Payment
		# Entry) must stay paid through submit.
		from non_profit.non_profit.custom_doctype.payment_entry import sync_donation_advance_paid

		sync_donation_advance_paid(self.name)

	def _validate_amount(self):
		# Controller-level invariant: every write path (public forms, portal,
		# imports, bank reconciliation, Desk) must produce a real amount. Python
		# and MariaDB both accept `inf`/`nan` doubles, and `nan` compares False
		# against every bound, so a caller-side `amount <= 0` check alone cannot
		# keep a non-finite value out of totals, allocations and receipts.
		amount = flt(self.amount)
		if not isfinite(amount):
			frappe.throw(_("Donation amount must be a finite number."))
		if amount <= 0:
			frappe.throw(_("Donation amount must be greater than zero."))

	def _validate_major_gift_donor(self):
		# A linked Major Gift must belong to the same Donor as this Donation.
		if not self.major_gift or not self.donor:
			return
		gift_donor = frappe.db.get_value("Major Gift", self.major_gift, "donor")
		if gift_donor and gift_donor != self.donor:
			frappe.throw(_("Major Gift {0} belongs to a different donor.").format(self.major_gift))

	def create_donor_for_website_user(self):
		from non_profit.non_profit.identity_lock import acquire_public_email_identity_lock

		acquire_public_email_identity_lock(frappe.session.user)
		donor_name = find_donor_by_email(frappe.session.user)

		if not donor_name:
			user = frappe.get_doc("User", frappe.session.user)
			donor = frappe.get_doc(
				doctype="Donor",
				donor_type=self.get("donor_type"),
				donor_name=user.get_fullname(),
			).insert(ignore_permissions=True)
			get_or_create_customer_for_donor(donor, email=frappe.session.user)
			donor_name = donor.name

		if self.get("__islocal"):
			self.donor = donor_name

	def on_payment_authorized(self, status_changed_to: str | None = None, *args, **kwargs):
		if status_changed_to not in (None, "Authorized", "Completed"):
			return
		# Idempotency: a duplicate or late gateway callback for an already-paid
		# donation must not re-run allocation. create_payment_entry() raises
		# "fully allocated" on such a donation, and the except-handler below
		# would then flip a genuinely-paid donation back to paid=0. Re-read the
		# stored flag so a stale in-memory instance cannot skip this guard.
		if frappe.db.get_value("Donation", self.name, "paid"):
			return
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
			self._dispatch_payment_thank_you()
		except Exception:
			frappe.log_error(
				title=f"Thank-you dispatch failed for {self.name}",
				message=frappe.get_traceback(),
			)
		try:
			from non_profit.non_profit.major_gifts import on_donation_change

			on_donation_change(self)
		except Exception:
			frappe.log_error(
				title=f"Donor roll-up refresh failed for {self.name}",
				message=frappe.get_traceback(),
			)

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
		# Trusted source: an Email Template document chosen in Non Profit
		# Settings — staff-authored content, the standard Frappe pattern.
		subject = frappe.render_template(template.subject, context)  # nosemgrep
		body = template.response or template.response_html or ""
		message = frappe.render_template(body, context)  # nosemgrep
		# Queue the email; the scheduler sends it. Avoid now=True since that
		# runs SMTP synchronously on commit and can break the payment flow.
		email_queue = send_referenced_email(
			recipients=[self.email],
			subject=subject,
			message=message,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)
		self._mark_thank_you_sent(email_queue=email_queue)
		return True

	def _dispatch_payment_thank_you(self) -> bool:
		"""Policy seam for presentation apps; settlement remains owned above."""
		return self._send_thank_you()

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
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage(
		"non_profit.non_profit.doctype.donation.donation.create_gateway_donation",
		getattr(donor, "name", None),
	)
	return legacy_payments.create_gateway_donation(donor, payment)


def get_donor(email):
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage("non_profit.non_profit.doctype.donation.donation.get_donor")
	return legacy_payments.get_gateway_donor(email)


@frappe.whitelist()
def create_donor(payment: dict) -> str:
	frappe.only_for(("Non Profit Manager", "Non Profit Member", "System Manager"))
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage("non_profit.non_profit.doctype.donation.donation.create_donor")
	return legacy_payments.create_gateway_donor(payment)


def get_company_for_donations():
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage(
		"non_profit.non_profit.doctype.donation.donation.get_company_for_donations"
	)
	return legacy_payments.get_company_for_donations()


def get_additional_notes(donor, donor_details):
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage(
		"non_profit.non_profit.doctype.donation.donation.get_additional_notes",
		getattr(donor, "name", None),
	)
	return legacy_payments.get_additional_gateway_notes(donor, donor_details)


def _is_sensitive_note_key(key: object) -> bool:
	from non_profit.non_profit.legacy_payments import is_sensitive_gateway_note_key

	return is_sensitive_gateway_note_key(key)


def _safe_note_text(notes: str) -> str:
	from non_profit.non_profit.legacy_payments import safe_gateway_note_text

	return safe_gateway_note_text(notes)


def create_mode_of_payment(method):
	from non_profit.non_profit import legacy_payments

	legacy_payments.log_legacy_payment_usage(
		"non_profit.non_profit.doctype.donation.donation.create_mode_of_payment"
	)
	legacy_payments.create_gateway_mode_of_payment(method)
