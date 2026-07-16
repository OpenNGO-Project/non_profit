# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest
from unittest.mock import patch

import erpnext
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, nowdate

from non_profit.non_profit.doctype.member.member import create_member
from non_profit.setup import ensure_non_profit_desk_roles


class TestNonProfitSetup(FrappeTestCase):
	def test_setup_disables_erpnext_test_loyalty_auto_opt_in(self):
		if not frappe.db.exists("DocType", "Loyalty Program"):
			self.skipTest("ERPNext Loyalty Program is not installed")

		from non_profit.non_profit.erpnext_loyalty import (
			ERP_NEXT_TEST_LOYALTY_PROGRAMS,
			disable_test_loyalty_auto_opt_in,
		)

		created = []
		originals = {}

		for loyalty_program in ERP_NEXT_TEST_LOYALTY_PROGRAMS:
			if not frappe.db.exists("Loyalty Program", loyalty_program):
				doc = frappe.get_doc(
					{
						"doctype": "Loyalty Program",
						"loyalty_program_name": loyalty_program,
						"loyalty_program_type": "Single Tier Program",
						"from_date": nowdate(),
						"auto_opt_in": 0,
						"collection_rules": [
							{
								"tier_name": "Standard",
								"min_spent": 0,
								"collection_factor": 1,
							}
						],
					}
				)
				doc.insert(ignore_permissions=True)
				created.append(loyalty_program)
			originals[loyalty_program] = frappe.db.get_value(
				"Loyalty Program", loyalty_program, "auto_opt_in"
			)
			frappe.db.set_value(
				"Loyalty Program",
				loyalty_program,
				"auto_opt_in",
				1,
				update_modified=False,
			)

		def restore_loyalty_programs():
			for loyalty_program in ERP_NEXT_TEST_LOYALTY_PROGRAMS:
				if loyalty_program in created and frappe.db.exists("Loyalty Program", loyalty_program):
					frappe.delete_doc(
						"Loyalty Program",
						loyalty_program,
						force=True,
						ignore_permissions=True,
					)
				elif frappe.db.exists("Loyalty Program", loyalty_program):
					frappe.db.set_value(
						"Loyalty Program",
						loyalty_program,
						"auto_opt_in",
						originals[loyalty_program],
						update_modified=False,
					)

		self.addCleanup(restore_loyalty_programs)

		disable_test_loyalty_auto_opt_in()

		for loyalty_program in ERP_NEXT_TEST_LOYALTY_PROGRAMS:
			self.assertEqual(
				frappe.db.get_value("Loyalty Program", loyalty_program, "auto_opt_in"),
				0,
			)

	def test_non_profit_roles_repair_sso_users_for_list_filters(self):
		role = "Non Profit Manager"
		original_desk_access = frappe.db.get_value("Role", role, "desk_access")
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Role", role, "desk_access", original_desk_access, update_modified=False
			)
		)

		frappe.db.set_value("Role", role, "desk_access", 0, update_modified=False)
		frappe.clear_cache(doctype="Role")

		user_email = "non-profit-sso-list-filter@example.com"
		if frappe.db.exists("User", user_email):
			user = frappe.get_doc("User", user_email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": user_email,
					"first_name": "Non Profit",
					"last_name": "SSO",
					"send_welcome_email": 0,
					"user_type": "Website User",
				}
			).insert(ignore_permissions=True)
		user.user_type = "Website User"
		user.set("roles", [])
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		frappe.clear_cache(user=user.name)

		self.assertFalse(frappe.has_permission("List Filter", "read", user=user.name))

		ensure_non_profit_desk_roles()
		frappe.clear_cache(user=user.name)

		self.assertEqual(frappe.db.get_value("Role", role, "desk_access"), 1)
		self.assertEqual(frappe.db.get_value("User", user.name, "user_type"), "System User")
		self.assertTrue(frappe.has_permission("List Filter", "read", user=user.name))


class TestMembershipMetadata(FrappeTestCase):
	def test_to_date_has_field_specific_translated_label(self):
		to_date = frappe.get_meta("Membership").get_field("to_date")

		self.assertEqual(to_date.label, "Membership Until")
		self.assertEqual(frappe._(to_date.label, lang="de"), "Mitgliedschaft bis")
		self.assertEqual(frappe._("Membership Details", lang="de"), "Mitgliedschaften")


class TestMembership(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Customer")
		plan = setup_membership()
		# make test member
		self.member_doc = create_member(
			frappe._dict(
				{
					"fullname": "_Test_Member",
					"email": "_test_member_erpnext@example.com",
					"membership_type": plan.name,
				}
			)
		)
		self.member_doc.make_customer_and_link()
		self.member = self.member_doc.name

	@unittest.skip(
		"Membership.invoice / paid fields dropped in the B2B/B2C refactor "
		"(a58cc79). generate_invoice() no longer writes back to a Membership "
		"field — payment lives on Sales Invoice. Test left in place as a "
		"marker; rewrite or remove when the new invoicing path lands."
	)
	def test_auto_generate_invoice_and_payment_entry(self):
		entry = make_membership(self.member)

		# Naive test to see if at all invoice was generated and attached to member
		# In any case if details were missing, the invoicing would throw an error
		invoice = entry.generate_invoice(save=True)
		self.assertEqual(invoice.name, entry.invoice)

	def test_renew_within_30_days(self):
		# First membership: today → today + 1 month (Monthly billing cycle).
		# Second renewal starts the day AFTER the first expires so the new
		# validate_no_overlap rule doesn't reject the boundary day.
		make_membership(self.member, {"from_date": nowdate()})
		make_membership(
			self.member,
			{"from_date": add_days(add_months(nowdate(), 1), 1)},
		)

		from frappe.utils.user import add_role

		add_role("test@example.com", "Non Profit Manager")
		frappe.set_user("test@example.com")

		# create next membership with expiry not within 30 days
		self.assertRaises(
			frappe.ValidationError,
			make_membership,
			self.member,
			{
				"from_date": add_months(nowdate(), 2),
			},
		)

		# Original test continued by re-running the same call as Administrator
		# to verify admin bypasses the 30-day rule. After the B2B/B2C refactor
		# the validate_no_overlap rule is also enforced (no admin bypass), so
		# those exact dates would now collide with the second membership above.
		# We're keeping the assertion for the 30-day check (the meat of the
		# test) and dropping the admin replay; coverage of admin overrides
		# belongs in a dedicated test if/when the bypass policy is settled.
		frappe.set_user("Administrator")

	def test_membership_can_keep_to_date_open(self):
		membership = frappe.get_doc(
			{
				"doctype": "Membership",
				"member": self.member,
				"membership_status": "Current",
				"membership_type": "_test_membership_type",
				"currency": frappe.db.get_value("Company", erpnext.get_default_company(), "default_currency"),
				"from_date": nowdate(),
				"amount": 100,
			}
		)
		membership.flags.keep_to_date_open = True
		membership.insert(ignore_permissions=True)

		self.assertFalse(membership.to_date)

	def test_invoice_generation_is_disabled_without_invoice_link_field(self):
		if frappe.get_meta("Membership").has_field("invoice"):
			self.skipTest("Legacy Membership.invoice field is installed")

		with open(
			frappe.get_app_path("non_profit", "non_profit", "doctype", "membership", "membership.js")
		) as handle:
			membership_script = handle.read()
		self.assertIn('frappe.meta.has_field(frm.doctype, "invoice")', membership_script)

		membership = make_membership(self.member)
		with patch("non_profit.non_profit.legacy_payments.frappe.logger") as logger:
			with self.assertRaises(frappe.ValidationError) as error:
				membership.generate_invoice(save=True)

		self.assertIn("Membership invoice generation is not available", str(error.exception))
		logger.return_value.warning.assert_called_once()

	def test_legacy_private_invoice_facade_logs_and_delegates(self):
		membership = make_membership(self.member)
		invoice = object()
		with (
			patch(
				"non_profit.non_profit.legacy_payments.generate_membership_invoice",
				return_value=invoice,
			) as generate_invoice,
			patch("non_profit.non_profit.legacy_payments.log_legacy_payment_usage") as log_usage,
		):
			result = membership._generate_invoice(save=False, with_payment_entry=True)

		self.assertIs(result, invoice)
		generate_invoice.assert_called_once_with(membership, save=False, with_payment_entry=True)
		log_usage.assert_called_once_with(
			"non_profit.non_profit.doctype.membership.membership.Membership._generate_invoice",
			membership.name,
		)

	def test_legacy_payment_entry_restores_account_permission_flag_on_failure(self):
		from non_profit.non_profit.legacy_payments import make_membership_payment_entry

		membership = make_membership(self.member)
		settings = frappe._dict(membership_payment_account="Legacy Cash")
		invoice = frappe._dict(name="SINV-LEGACY", grand_total=100)
		original_flag = getattr(frappe.flags, "ignore_account_permission", False)
		frappe.flags.ignore_account_permission = False
		try:
			with patch(
				"erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				side_effect=RuntimeError("legacy payment failure"),
			):
				with self.assertRaises(RuntimeError):
					make_membership_payment_entry(membership, settings, invoice)
			self.assertFalse(frappe.flags.ignore_account_permission)
		finally:
			frappe.flags.ignore_account_permission = original_flag

	def test_ensure_membership_subscription_creates_open_ended_subscription(self):
		from non_profit.non_profit.membership_subscription import (
			ensure_membership_subscription,
		)

		membership = frappe.get_doc(
			{
				"doctype": "Membership",
				"member": self.member,
				"membership_status": "Current",
				"membership_type": "_test_membership_type",
				"currency": frappe.db.get_value("Company", erpnext.get_default_company(), "default_currency"),
				"from_date": nowdate(),
				"amount": 100,
			}
		)
		membership.flags.keep_to_date_open = True
		membership.insert(ignore_permissions=True)

		subscription = ensure_membership_subscription(membership)
		membership.reload()
		subscription_doc = frappe.get_doc("Subscription", subscription)

		self.assertEqual(membership.subscription, subscription)
		self.assertFalse(membership.to_date)
		self.assertEqual(subscription_doc.party_type, "Customer")
		self.assertEqual(subscription_doc.party, self.member_doc.customer)
		self.assertEqual(
			subscription_doc.company,
			frappe.db.get_single_value("Non Profit Settings", "company"),
		)
		self.assertEqual(subscription_doc.start_date, membership.from_date)
		self.assertFalse(subscription_doc.end_date)

	def test_ensure_membership_subscription_skips_non_subscription_type(self):
		from non_profit.non_profit.membership_subscription import (
			ensure_membership_subscription,
		)

		frappe.db.set_value(
			"Membership Type",
			"_test_membership_type",
			"is_subscription",
			0,
			update_modified=False,
		)
		membership = frappe.get_doc(
			{
				"doctype": "Membership",
				"member": self.member,
				"membership_status": "Current",
				"membership_type": "_test_membership_type",
				"currency": frappe.db.get_value("Company", erpnext.get_default_company(), "default_currency"),
				"from_date": nowdate(),
				"amount": 100,
			}
		)
		membership.flags.keep_to_date_open = True
		membership.insert(ignore_permissions=True)

		self.assertIsNone(ensure_membership_subscription(membership))
		membership.reload()
		self.assertFalse(membership.subscription)

	def tearDown(self):
		frappe.db.rollback()


def set_config(key, value):
	frappe.db.set_value("Non Profit Settings", None, key, value)


def make_membership(member, payload=None):
	payload = payload or {}
	company = frappe.db.get_single_value("Non Profit Settings", "company")
	currency = frappe.db.get_value("Company", company, "default_currency") if company else "USD"

	data = {
		"doctype": "Membership",
		"member": member,
		"membership_status": "Current",
		"membership_type": "_test_membership_type",
		"currency": currency,
		"from_date": nowdate(),
		"amount": 100,
	}
	data.update(payload)
	membership = frappe.get_doc(data)
	membership.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return membership


def create_item(item_code):
	if not frappe.db.exists("Item", item_code):
		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_code
		item.stock_uom = "Nos"
		item.description = item_code
		item.item_group = "All Item Groups"
		item.is_stock_item = 0
		item.save()
	else:
		item = frappe.get_doc("Item", item_code)
	return item


def setup_membership():
	# Get default company
	company = frappe.get_doc("Company", erpnext.get_default_company())

	# update non profit settings
	settings = frappe.get_doc("Non Profit Settings")
	settings.billing_cycle = "Monthly"
	# Enable invoicing
	settings.allow_invoicing = 1
	settings.automate_membership_payment_entries = 1
	settings.company = company.name
	settings.donation_company = company.name
	settings.membership_payment_account = company.default_cash_account
	settings.membership_debit_account = company.default_receivable_account
	settings.flags.ignore_mandatory = True
	settings.save()

	# make test plan
	if not frappe.db.exists("Membership Type", "_test_membership_type"):
		plan = frappe.new_doc("Membership Type")
		plan.membership_type = "_test_membership_type"
		plan.amount = 100
		plan.linked_item = create_item("_Test Item for Non Profit Membership").name
		plan.is_subscription = 1
		plan.insert()
	else:
		plan = frappe.get_doc("Membership Type", "_test_membership_type")
		plan.is_subscription = 1
		plan.save(ignore_permissions=True)

	return plan
