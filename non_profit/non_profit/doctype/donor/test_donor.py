# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestDonor(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_get_or_create_customer_for_donor_creates_customer_and_contact_links(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_customer_for_donor

		email = f"donor-customer-{frappe.generate_hash(length=8)}@example.org"
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Donor Customer",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)

		get_or_create_customer_for_donor(donor, email=email)
		donor.reload()

		self.assertFalse(frappe.get_meta("Donor").has_field("email"))
		self.assertTrue(donor.customer)
		self.assertEqual(frappe.db.get_value("Customer", donor.customer, "email_id"), email)
		contact = frappe.db.get_value(
			"Dynamic Link",
			{"parenttype": "Contact", "link_doctype": "Donor", "link_name": donor.name},
			"parent",
		)
		self.assertTrue(contact)
		self.assertTrue(
			frappe.db.exists(
				"Dynamic Link",
				{
					"parenttype": "Contact",
					"parent": contact,
					"link_doctype": "Customer",
					"link_name": donor.customer,
				},
			)
		)
		self.assertEqual(frappe.db.get_value("Customer", donor.customer, "customer_primary_contact"), contact)

	def test_donor_reuses_member_customer_by_email(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_customer_for_donor

		email = f"shared-donor-member-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Shared Donor Member")
		frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": "Shared Person",
				"membership_type": self._membership_type(),
				"email_id": email,
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Shared Person",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)

		self.assertEqual(get_or_create_customer_for_donor(donor, email=email), customer.name)
		donor.reload()
		self.assertEqual(donor.customer, customer.name)

	def test_get_donor_email_reads_linked_customer(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import find_donor_by_email, get_donor_email

		email = f"customer-email-donor-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Customer Email Donor")
		frappe.db.set_value("Customer", customer.name, "email_id", email, update_modified=False)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Customer Email Donor",
				"donor_type": self._donor_type(),
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(get_donor_email(donor), email)
		self.assertEqual(find_donor_by_email(email), donor.name)

	def _donor_type(self) -> str:
		name = f"Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name

	def _membership_type(self) -> str:
		name = f"Membership Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Membership Type", "membership_type": name, "amount": 10}).insert(
			ignore_permissions=True
		)
		return name

	def _customer(self, customer_name: str):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer_name,
				"customer_type": "Individual",
				"customer_group": self._customer_group(),
				"territory": self._territory(),
			}
		)
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		return customer

	def _customer_group(self) -> str | None:
		return (
			frappe.db.get_single_value("Selling Settings", "customer_group")
			or frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name asc")
			or frappe.db.get_value("Customer Group", {}, "name", order_by="lft asc")
		)

	def _territory(self) -> str | None:
		return (
			frappe.db.get_single_value("Selling Settings", "territory")
			or frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
		)
