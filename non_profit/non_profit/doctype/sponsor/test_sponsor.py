from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSponsor(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_create_sponsor_from_contact_and_customer_creates_donor_links(self) -> None:
		from non_profit.non_profit.doctype.sponsor.sponsor import create_sponsor_from_identity

		email = f"sponsor-contact-customer-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Sponsor Customer")
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Sponsor",
				"last_name": "Contact",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		result = create_sponsor_from_identity(
			contact=contact.name,
			customer=customer.name,
			donor_type=self._donor_type(),
		)

		sponsor = frappe.get_doc("Sponsor", result["sponsor"])
		donor = frappe.get_doc("Donor", result["donor"])
		self.assertEqual(sponsor.donor, donor.name)
		self.assertEqual(donor.customer, customer.name)
		self.assertTrue(
			frappe.db.exists(
				"Dynamic Link",
				{
					"parenttype": "Contact",
					"parent": contact.name,
					"link_doctype": "Donor",
					"link_name": donor.name,
				},
			)
		)

	def test_create_sponsor_from_identity_requires_create_permission(self) -> None:
		from non_profit.non_profit.doctype.sponsor.sponsor import create_sponsor_from_identity

		customer = self._customer("Sponsor Permission Customer")

		with patch(
			"non_profit.non_profit.doctype.sponsor.sponsor.frappe.has_permission",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				create_sponsor_from_identity(customer=customer.name, donor_type=self._donor_type())

	def _donor_type(self) -> str:
		name = f"Sponsor Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
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
		return frappe.db.get_single_value("Selling Settings", "territory") or frappe.db.get_value(
			"Territory", {}, "name", order_by="lft asc"
		)
