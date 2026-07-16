"""Tests for non_profit.non_profit.membership_sync.

Covers:
  - validate_no_overlap rejects an active Membership overlapping another for the same Member
  - overlap ignores Cancelled/Expired rows
  - overlap treats an open-ended (perpetual) to_date as +∞
  - get_customer_for_membership resolves via member.customer
  - list_customer_memberships enumerates Memberships by Customer
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import add_months, nowdate


def _ensure_membership_type() -> str:
	name = "Sync Test Membership Type"
	if frappe.db.exists("Membership Type", name):
		return name
	doc = frappe.new_doc("Membership Type")
	doc.membership_type = name
	doc.amount = 10
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_customer(name: str = "Sync Test Customer") -> str:
	existing = frappe.db.exists("Customer", {"customer_name": name})
	if existing:
		return existing
	doc = frappe.new_doc("Customer")
	doc.customer_name = name
	doc.customer_type = "Company"
	doc.customer_group = frappe.db.get_value(
		"Customer Group", {"is_group": 0}, "name"
	) or frappe.db.get_value("Customer Group", {}, "name")
	doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or frappe.db.get_value(
		"Territory", {}, "name"
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_member(customer: str | None = None, label: str = "Sync Test Member") -> str:
	filters = {"member_name": label}
	if customer:
		filters["customer"] = customer
	existing = frappe.db.exists("Member", filters)
	if existing:
		return existing
	doc = frappe.new_doc("Member")
	doc.member_name = label
	if customer:
		doc.customer = customer
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_membership(
	member: str,
	status: str = "Current",
	from_date: str | None = None,
	to_date: str | None = None,
	warn_on_overlap: bool = False,
):
	doc = frappe.new_doc("Membership")
	doc.member = member
	doc.membership_type = _ensure_membership_type()
	doc.membership_status = status
	doc.from_date = from_date or nowdate()
	# to_date optional — leave None for perpetual
	if to_date is not None:
		doc.to_date = to_date
	else:
		doc.to_date = add_months(nowdate(), 12)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_permissions = True
	if warn_on_overlap:
		doc.flags.warn_on_membership_overlap = True
	doc.insert(ignore_permissions=True)
	return doc


class TestMembershipSync(unittest.TestCase):
	"""Plain unittest TestCase — avoids ERPNext's FrappeTestCase bootstrap
	which creates test Companies / Price Lists. We don't need that fixture
	data, and it often fails on dev sites with prior-run data pollution.
	We roll back each test manually."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_overlap_rejects_same_member_current_period(self):
		member = _ensure_member(label="Overlap A")
		_make_membership(member, from_date=nowdate(), to_date=add_months(nowdate(), 12))
		with self.assertRaises(frappe.ValidationError):
			_make_membership(
				member,
				from_date=add_months(nowdate(), 6),
				to_date=add_months(nowdate(), 18),
			)

	def test_overlap_warn_flag_allows_same_member_current_period(self):
		member = _ensure_member(label="Overlap Warning")
		_make_membership(member, from_date=nowdate(), to_date=add_months(nowdate(), 12))
		second = _make_membership(
			member,
			from_date=add_months(nowdate(), 6),
			to_date=add_months(nowdate(), 18),
			warn_on_overlap=True,
		)
		self.assertTrue(second.name)

	def test_overlap_allows_non_overlapping_periods(self):
		member = _ensure_member(label="Overlap B")
		_make_membership(member, from_date=nowdate(), to_date=add_months(nowdate(), 6))
		# Starts after the first ends — no overlap.
		second = _make_membership(
			member,
			from_date=add_months(nowdate(), 7),
			to_date=add_months(nowdate(), 12),
		)
		self.assertTrue(second.name)

	def test_overlap_allows_cancelled_or_expired(self):
		member = _ensure_member(label="Overlap C")
		_make_membership(
			member,
			status="Cancelled",
			from_date=nowdate(),
			to_date=add_months(nowdate(), 12),
		)
		# Active one overlapping the cancelled — should succeed.
		second = _make_membership(
			member,
			status="Current",
			from_date=nowdate(),
			to_date=add_months(nowdate(), 12),
		)
		self.assertTrue(second.name)

	def test_perpetual_membership_overlap_is_detected(self):
		member = _ensure_member(label="Perpetual A")
		# First membership is perpetual (to_date=None).
		_make_membership(member, from_date=nowdate(), to_date="")
		# Any later membership in the same/later period should overlap.
		with self.assertRaises(frappe.ValidationError):
			_make_membership(
				member,
				from_date=add_months(nowdate(), 6),
				to_date=add_months(nowdate(), 18),
			)

	def test_get_customer_for_membership_via_member(self):
		from non_profit.non_profit.membership_sync import get_customer_for_membership

		customer = _ensure_customer(name="Resolve Test Customer")
		member = _ensure_member(customer=customer, label="Resolver")
		m = _make_membership(member)
		self.assertEqual(get_customer_for_membership(m), customer)
		self.assertEqual(get_customer_for_membership(m.name), customer)

	def test_list_customer_memberships(self):
		from non_profit.non_profit.membership_sync import list_customer_memberships

		customer = _ensure_customer(name="List Test Customer")
		member = _ensure_member(customer=customer, label="Lister")
		m = _make_membership(member)
		rows = list_customer_memberships(customer)
		self.assertIn(m.name, [r["name"] for r in rows])
