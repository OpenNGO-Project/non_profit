# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestDonor(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_get_or_create_customer_for_donor_creates_customer_and_contact_links(
		self,
	) -> None:
		from non_profit.non_profit.doctype.donor.donor import (
			get_or_create_customer_for_donor,
		)

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
		self.assertEqual(
			frappe.db.get_value("Customer", donor.customer, "customer_primary_contact"),
			contact,
		)

	def test_donor_reuses_member_customer_by_email(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import (
			get_or_create_customer_for_donor,
		)

		email = f"shared-donor-member-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Shared Donor Member")
		frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": "Shared Person",
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

	def test_donor_pan_details_removed_from_schema_and_setup(self) -> None:
		from non_profit.setup import get_custom_fields

		self.assertFalse(frappe.db.exists("Custom Field", "Donor-pan_number"))
		self.assertFalse(frappe.get_meta("Donor").has_field("pan_number"))
		self.assertFalse(frappe.db.has_column("Donor", "pan_number"))
		self.assertNotIn("Donor", get_custom_fields())

	def test_donor_payment_notes_do_not_store_pan_details(self) -> None:
		from non_profit.non_profit.doctype.donation.donation import get_additional_notes

		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Sensitive Notes Donor",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)

		get_additional_notes(
			donor,
			frappe._dict(
				notes={
					"name": "Sensitive Notes Donor",
					"pan": "SECRET-PAN",
					"purpose": "General donation",
				}
			),
		)

		comments = "\n".join(
			frappe.get_all(
				"Comment",
				filters={"reference_doctype": "Donor", "reference_name": donor.name},
				pluck="content",
			)
		)
		self.assertNotIn("SECRET-PAN", comments)
		self.assertNotIn("pan", comments.lower())
		self.assertIn("General donation", comments)

	def test_create_donor_from_identity_requires_create_permission(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import create_donor_from_identity

		customer = self._customer("Donor Permission Customer")

		with patch(
			"non_profit.non_profit.doctype.donor.donor.frappe.has_permission",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				create_donor_from_identity(customer=customer.name, donor_type=self._donor_type())

	def test_create_donor_from_contact_and_customer_links_both(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import create_donor_from_identity

		email = f"donor-contact-customer-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Donor Contact Customer")
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Donor",
				"last_name": "Contact",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		result = create_donor_from_identity(
			contact=contact.name,
			customer=customer.name,
			donor_type=self._donor_type(),
		)

		donor = frappe.get_doc("Donor", result["donor"])
		self.assertEqual(donor.customer, customer.name)
		for link_doctype, link_name in (("Donor", donor.name), ("Customer", customer.name)):
			self.assertTrue(
				frappe.db.exists(
					"Dynamic Link",
					{
						"parenttype": "Contact",
						"parent": contact.name,
						"link_doctype": link_doctype,
						"link_name": link_name,
					},
				)
			)

	def test_create_donor_from_identity_rejects_conflicting_contact_customer_links(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import create_donor_from_identity

		email = f"donor-conflict-{frappe.generate_hash(length=8)}@example.org"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Donor",
				"last_name": "Conflict",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		donor_type = self._donor_type()
		linked_donor = frappe.get_doc(
			{"doctype": "Donor", "donor_name": "Linked Donor", "donor_type": donor_type}
		).insert(ignore_permissions=True)
		contact.append("links", {"link_doctype": "Donor", "link_name": linked_donor.name})
		contact.save(ignore_permissions=True)
		customer = self._customer("Donor Conflict Customer")
		frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Customer Donor",
				"donor_type": donor_type,
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			create_donor_from_identity(contact=contact.name, customer=customer.name, donor_type=donor_type)

	def test_contact_only_donor_email_reads_linked_contact(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import (
			get_donor_email,
			get_or_create_donor_for_contact,
		)

		email = f"donor-contact-only-{frappe.generate_hash(length=8)}@example.org"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Contact",
				"last_name": "Only",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		donor = get_or_create_donor_for_contact(
			contact.name, donor_type=self._donor_type(), ignore_permissions=True
		)

		self.assertFalse(donor.customer)
		self.assertEqual(get_donor_email(donor), email)

	def test_get_donor_email_reads_linked_customer(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import (
			find_donor_by_email,
			get_donor_email,
		)

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

	def test_donor_customer_backfill_patch_runs_after_model_sync(self) -> None:
		from frappe.modules.patch_handler import PatchType, get_patches_from_app

		patch_name = "non_profit.patches.backfill_donor_customers_from_email"

		self.assertNotIn(patch_name, get_patches_from_app("non_profit", PatchType.pre_model_sync))
		self.assertIn(patch_name, get_patches_from_app("non_profit", PatchType.post_model_sync))

	def test_donor_customer_backfill_patch_skips_until_customer_column_exists(
		self,
	) -> None:
		from non_profit.patches import backfill_donor_customers_from_email

		def has_column(doctype: str, fieldname: str) -> bool:
			return doctype == "Donor" and fieldname == "email"

		with (
			patch.object(
				backfill_donor_customers_from_email.frappe.db,
				"exists",
				return_value=True,
			),
			patch.object(
				backfill_donor_customers_from_email.frappe.db,
				"has_column",
				side_effect=has_column,
			),
			patch.object(backfill_donor_customers_from_email.frappe, "get_all") as get_all,
		):
			backfill_donor_customers_from_email.execute()

		get_all.assert_not_called()

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
		return frappe.db.get_single_value("Selling Settings", "territory") or frappe.db.get_value(
			"Territory", {}, "name", order_by="lft asc"
		)
