# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	add_years,
	get_link_to_form,
	getdate,
	nowdate,
)

from non_profit.non_profit.mailer import send_referenced_email


class Membership(Document):
	def validate(self):
		# Member is the canonical identity for a Membership. For B2B flows,
		# create the Member up front (pointing at the Customer) before binding
		# a Membership to it.
		if not self.member or not frappe.db.exists("Member", self.member):
			user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
			if user_type == "Website User":
				self.create_member_from_website_user()
			else:
				frappe.throw(_("Please select a Member"))

		# Read-only household flag: synced from Member.household, which the
		# Household controller maintains. Household saves also refresh this flag
		# on non-expired Memberships of affected Members.
		self.is_household_membership = bool(
			self.member and frappe.db.get_value("Member", self.member, "household")
		)

		self.validate_membership_period()

	def create_member_from_website_user(self):
		member_name = frappe.get_value("Member", dict(email_id=frappe.session.user))

		if not member_name:
			user = frappe.get_doc("User", frappe.session.user)
			member = frappe.get_doc(
				dict(
					doctype="Member",
					email_id=frappe.session.user,
					member_name=user.get_fullname(),
				)
			).insert(ignore_permissions=True)
			member_name = member.name

		if self.get("__islocal"):
			self.member = member_name

	def validate_membership_period(self):
		last_membership = get_last_membership(self.member)

		if (
			last_membership
			and last_membership.name != self.name
			and frappe.session.user != "Administrator"
			and last_membership.to_date
		):
			if getdate(add_days(last_membership.to_date, -30)) > getdate(nowdate()):
				frappe.throw(_("You can only renew if your membership expires within 30 days"))

			if not getattr(self.flags, "keep_from_date", False):
				self.from_date = add_days(last_membership.to_date, 1)

		# Public/client apps may explicitly request an open-ended membership.
		# Keep that generic signal here so presentation apps do not need to
		# fight the default billing-cycle date fill after insert.
		if not self.to_date and not getattr(self.flags, "keep_to_date_open", False):
			billing_cycle = frappe.db.get_single_value("Non Profit Settings", "billing_cycle")
			if billing_cycle == "Yearly":
				self.to_date = add_years(self.from_date, 1)
			elif billing_cycle == "Monthly":
				self.to_date = add_months(self.from_date, 1)

	def on_payment_authorized(self, status_changed_to=None):
		from non_profit.non_profit.legacy_payments import (
			authorize_membership_payment,
			log_legacy_payment_usage,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership.Membership.on_payment_authorized",
			self.name,
		)
		return authorize_membership_payment(self, status_changed_to)

	@frappe.whitelist()
	def generate_invoice(self, save: bool = True, with_payment_entry: bool = False) -> Any:
		# run_doc_method only enforces read permission; creating and
		# submitting a Sales Invoice is a write-level action.
		self.check_permission("write")
		from non_profit.non_profit.legacy_payments import (
			generate_membership_invoice,
			log_legacy_payment_usage,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership.Membership.generate_invoice",
			self.name,
		)
		return generate_membership_invoice(self, save=save, with_payment_entry=with_payment_entry)

	def _generate_invoice(self, save: bool = True, with_payment_entry: bool = False) -> Any:
		from non_profit.non_profit.legacy_payments import (
			generate_membership_invoice,
			log_legacy_payment_usage,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership.Membership._generate_invoice",
			self.name,
		)
		return generate_membership_invoice(self, save=save, with_payment_entry=with_payment_entry)

	def validate_membership_type_and_settings(self, plan, settings):
		from non_profit.non_profit.legacy_payments import (
			log_legacy_payment_usage,
			validate_membership_invoice_settings,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership."
			"Membership.validate_membership_type_and_settings",
			self.name,
		)
		return validate_membership_invoice_settings(self, plan, settings)

	def make_payment_entry(self, settings, invoice):
		from non_profit.non_profit.legacy_payments import (
			log_legacy_payment_usage,
			make_membership_payment_entry,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership.Membership.make_payment_entry",
			self.name,
		)
		return make_membership_payment_entry(self, settings, invoice)

	@frappe.whitelist()
	def send_acknowlement(self) -> None:
		# run_doc_method only enforces read permission; sending member email
		# is a write-level action.
		self.check_permission("write")
		self._send_acknowlement()

	def _send_acknowlement(self) -> None:
		settings = frappe.get_doc("Non Profit Settings")
		if not settings.send_email:
			frappe.throw(
				_("You need to enable <b>Send Acknowledge Email</b> in {0}").format(
					get_link_to_form("Non Profit Settings", "Non Profit Settings")
				)
			)

		member = frappe.get_doc("Member", self.member)
		if not member.email_id:
			frappe.throw(
				_("Email address of member {0} is missing").format(
					frappe.utils.get_link_to_form("Member", self.member)
				)
			)

		email = member.email_id
		attachments = [
			frappe.attach_print("Membership", self.name, print_format=settings.membership_print_format)
		]

		linked_invoice = self.get("invoice") if self.meta.has_field("invoice") else None
		if linked_invoice and settings.send_invoice:
			attachments.append(
				frappe.attach_print(
					"Sales Invoice",
					linked_invoice,
					print_format=settings.inv_print_format,
				)
			)

		email_template = frappe.get_doc("Email Template", settings.email_template)
		context = {"doc": self, "member": member}

		email_args = {
			"recipients": [email],
			"message": frappe.render_template(email_template.get("response"), context),
			"subject": frappe.render_template(email_template.get("subject"), context),
			"attachments": attachments,
			"reference_doctype": self.doctype,
			"reference_name": self.name,
		}

		if not frappe.flags.in_test:
			frappe.enqueue(
				method="non_profit.non_profit.mailer.send_referenced_email",
				queue="short",
				timeout=300,
				is_async=True,
				**email_args,
			)
		else:
			send_referenced_email(**email_args)

	def generate_and_send_invoice(self):
		from non_profit.non_profit.legacy_payments import (
			generate_membership_invoice,
			log_legacy_payment_usage,
		)

		log_legacy_payment_usage(
			"non_profit.non_profit.doctype.membership.membership.Membership.generate_and_send_invoice",
			self.name,
		)
		generate_membership_invoice(self, save=False)
		self._send_acknowlement()


def make_invoice(membership, member, plan, settings):
	from non_profit.non_profit.legacy_payments import (
		log_legacy_payment_usage,
		make_membership_invoice,
	)

	log_legacy_payment_usage(
		"non_profit.non_profit.doctype.membership.membership.make_invoice",
		membership.name,
	)
	return make_membership_invoice(membership, member, plan, settings)


def get_company_for_memberships():
	company = frappe.db.get_single_value("Non Profit Settings", "company")
	if not company:
		from non_profit.non_profit.utils import get_company

		company = get_company()
	return company


def set_expired_status():
	membership = frappe.qb.DocType("Membership")
	(
		frappe.qb.update(membership)
		.set(membership.membership_status, "Expired")
		.where(membership.membership_status.notin(("Cancelled", "Expired")))
		.where(membership.to_date < nowdate())
	).run()


def get_last_membership(member):
	"""Returns last membership if exists"""
	if not member:
		return None
	# `paid=1` filter dropped — column removed in B2B/B2C refactor (a58cc79);
	# payment state lives on Sales Invoice.
	last_membership = frappe.get_all(
		"Membership",
		"name,to_date,membership_type",
		dict(member=member),
		order_by="to_date desc",
		limit=1,
	)

	if last_membership:
		return last_membership[0]
