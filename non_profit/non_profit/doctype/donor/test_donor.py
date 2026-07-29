# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Contact",
	"Customer",
	"Donor Type",
	"Household",
	"Language",
	"User",
]


class TestDonor(IntegrationTestCase):
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
		self.assertEqual(donor.subject_type, "Individual")
		self.assertEqual(donor.contact, contact)
		self.assertEqual(frappe.db.get_value("Contact", contact, "npo_identity_kind"), "Person")

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

	def test_customer_only_company_donor_remains_organization(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_donor_for_customer

		customer = self._customer("Organization Donor Customer")
		frappe.db.set_value("Customer", customer.name, "customer_type", "Company", update_modified=False)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Organization Mailbox",
				"npo_identity_kind": "Generic Endpoint",
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Customer", customer.name, "customer_primary_contact", contact.name, update_modified=False
		)

		donor = get_or_create_donor_for_customer(
			customer.name, donor_type=self._donor_type(), ignore_permissions=True
		)

		self.assertEqual(donor.subject_type, "Organization")
		self.assertFalse(donor.contact)
		self.assertEqual(
			frappe.db.get_value("Contact", contact.name, "npo_identity_kind"), "Generic Endpoint"
		)
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

	def test_existing_company_donor_customer_linking_repairs_organization_subject(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_customer_for_donor

		customer = self._customer("Legacy Organization Donor Customer")
		frappe.db.set_value("Customer", customer.name, "customer_type", "Company", update_modified=False)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Legacy Organization Mailbox",
				"npo_identity_kind": "Generic Endpoint",
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Customer", customer.name, "customer_primary_contact", contact.name, update_modified=False
		)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Legacy Organization Donor",
				"donor_type": self._donor_type(),
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)

		get_or_create_customer_for_donor(donor)
		donor.reload()

		self.assertEqual(donor.subject_type, "Organization")
		self.assertFalse(donor.contact)
		self.assertEqual(
			frappe.db.get_value("Contact", contact.name, "npo_identity_kind"), "Generic Endpoint"
		)

	def test_organization_contact_link_does_not_block_individual_donor_role(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import (
			get_or_create_donor_for_contact,
			get_or_create_donor_for_customer,
		)

		email = f"organization-contact-person-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Organization With Individual Donor Contact")
		frappe.db.set_value("Customer", customer.name, "customer_type", "Company", update_modified=False)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Organization Contact Person",
				"email_ids": [{"email_id": email, "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Customer", customer.name, "customer_primary_contact", contact.name, update_modified=False
		)
		organization_donor = get_or_create_donor_for_customer(
			customer.name, donor_type=self._donor_type(), ignore_permissions=True
		)

		individual_donor = get_or_create_donor_for_contact(
			contact.name, donor_type=self._donor_type(), ignore_permissions=True
		)

		self.assertNotEqual(individual_donor.name, organization_donor.name)
		self.assertEqual(individual_donor.subject_type, "Individual")
		self.assertEqual(individual_donor.contact, contact.name)

	def test_household_donor_service_creates_and_reuses_one_donor(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_donor_for_household

		household = frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": f"Household Donor {frappe.generate_hash(length=8)}",
			}
		).insert(ignore_permissions=True)
		donor_type = self._donor_type()

		donor = get_or_create_donor_for_household(
			household.name,
			donor_type=donor_type,
			ignore_permissions=True,
		)
		reused = get_or_create_donor_for_household(
			household.name,
			donor_type=donor_type,
			ignore_permissions=True,
		)

		self.assertEqual(reused.name, donor.name)
		self.assertEqual(donor.donor_name, household.household_name)
		self.assertEqual(donor.subject_type, "Household")
		self.assertEqual(donor.subject_household, household.name)
		self.assertEqual(donor.household, household.name)
		self.assertFalse(donor.customer)

	def test_household_donor_service_reuses_unique_legacy_blank_subject_type(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_donor_for_household

		household = frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": f"Legacy Household Donor {frappe.generate_hash(length=8)}",
			}
		).insert(ignore_permissions=True)
		legacy_donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Legacy Household Donor",
				"donor_type": self._donor_type(),
				"subject_household": household.name,
			}
		).insert(ignore_permissions=True)

		reused = get_or_create_donor_for_household(household.name, ignore_permissions=True)

		self.assertEqual(reused.name, legacy_donor.name)
		self.assertFalse(reused.subject_type)
		self.assertEqual(
			frappe.db.count("Donor", {"subject_household": household.name}),
			1,
		)

	def test_household_donor_service_rejects_existing_conflict(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_or_create_donor_for_household

		household = frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": f"Conflicting Household Donor {frappe.generate_hash(length=8)}",
			}
		).insert(ignore_permissions=True)
		donor_type = self._donor_type()
		for suffix, subject_type in (("One", "Household"), ("Two", None)):
			frappe.get_doc(
				{
					"doctype": "Donor",
					"donor_name": f"Household Donor {suffix}",
					"donor_type": donor_type,
					"subject_type": subject_type,
					"subject_household": household.name,
				}
			).insert(ignore_permissions=True)

		with self.assertRaisesRegex(frappe.ValidationError, "more than one active Household Donor"):
			get_or_create_donor_for_household(household.name, ignore_permissions=True)

	def test_policy_identity_service_rejects_ambiguous_donor_email(self) -> None:
		from non_profit.non_profit.donor_identity import resolve_donor_customer_identity

		email = f"ambiguous-donor-{frappe.generate_hash(length=8)}@example.org"
		donor_type = self._donor_type()
		for suffix in ("One", "Two"):
			customer = self._customer(f"Ambiguous Donor {suffix}")
			frappe.db.set_value("Customer", customer.name, "email_id", email, update_modified=False)
			frappe.get_doc(
				{
					"doctype": "Donor",
					"donor_name": f"Ambiguous Donor {suffix}",
					"donor_type": donor_type,
					"customer": customer.name,
				}
			).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			resolve_donor_customer_identity(
				donor_name="Ambiguous Donor",
				email=email,
				donor_type=donor_type,
				ambiguous_email_policy="reject",
			)

	def test_policy_identity_service_rejects_ambiguous_customer_email(self) -> None:
		from non_profit.non_profit.donor_identity import resolve_donor_customer_identity

		email = f"ambiguous-customer-{frappe.generate_hash(length=8)}@example.org"
		for suffix in ("One", "Two"):
			customer = self._customer(f"Ambiguous Customer {suffix}")
			frappe.db.set_value("Customer", customer.name, "email_id", email, update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			resolve_donor_customer_identity(
				donor_name="Ambiguous Customer",
				email=email,
				donor_type=self._donor_type(),
				ambiguous_email_policy="reject",
			)

	def test_policy_identity_service_deduplicates_member_customer_candidates(self) -> None:
		from non_profit.non_profit.donor_identity import resolve_donor_customer_identity

		email = f"shared-member-customer-{frappe.generate_hash(length=8)}@example.org"
		customer = self._customer("Shared Member Customer")
		for suffix in ("One", "Two"):
			frappe.get_doc(
				{
					"doctype": "Member",
					"member_name": f"Shared Member {suffix}",
					"email_id": email,
					"customer": customer.name,
				}
			).insert(ignore_permissions=True)

		donor, resolved_customer = resolve_donor_customer_identity(
			donor_name="Shared Member",
			email=email,
			donor_type=self._donor_type(),
			ambiguous_email_policy="reject",
		)

		self.assertEqual(resolved_customer, customer.name)
		self.assertEqual(donor.customer, customer.name)

	def test_policy_identity_service_applies_creation_providers(self) -> None:
		from non_profit.non_profit.donor_identity import resolve_donor_customer_identity

		email = f"policy-provider-{frappe.generate_hash(length=8)}@example.org"
		inserted_values = {}

		def insert_donor(values: dict):
			inserted_values.update(values)
			return frappe.get_doc(values).insert(ignore_permissions=True)

		donor, customer = resolve_donor_customer_identity(
			donor_name="Policy Provider",
			email=email,
			donor_type=self._donor_type(),
			donor_values_provider=lambda values: {**values, "receipt_delivery": "Email"},
			customer_values_provider=lambda values: {**values, "email_id": email},
			donor_inserter=insert_donor,
		)

		self.assertEqual(inserted_values["receipt_delivery"], "Email")
		self.assertEqual(donor.receipt_delivery, "Email")
		self.assertEqual(donor.customer, customer)
		self.assertEqual(frappe.db.get_value("Customer", customer, "email_id"), email)

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
		self.assertEqual(donor.subject_type, "Individual")
		self.assertEqual(donor.contact, contact.name)
		self.assertEqual(frappe.db.get_value("Contact", contact.name, "npo_identity_kind"), "Person")
		self.assertEqual(get_donor_email(donor), email)

	def test_individual_donor_email_prefers_canonical_contact(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import get_donor_email

		customer = self._customer("Canonical Contact Email Donor")
		frappe.db.set_value(
			"Customer", customer.name, "email_id", "customer@example.org", update_modified=False
		)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Canonical Email",
				"email_ids": [{"email_id": "person@example.org", "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Canonical Contact Email Donor",
				"donor_type": self._donor_type(),
				"customer": customer.name,
				"subject_type": "Individual",
				"contact": contact.name,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(get_donor_email(donor), "person@example.org")

	def test_individual_donor_rejects_a_second_linked_contact(self) -> None:
		from non_profit.non_profit.doctype.donor.donor import ensure_contact_link

		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Conflicting Linked Contact Donor",
				"donor_type": self._donor_type(),
			}
		).insert(ignore_permissions=True)
		first_contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "First Linked Contact",
				"links": [{"link_doctype": "Donor", "link_name": donor.name}],
			}
		).insert(ignore_permissions=True)
		second_contact = frappe.get_doc({"doctype": "Contact", "first_name": "Second Linked Contact"}).insert(
			ignore_permissions=True
		)

		with self.assertRaisesRegex(frappe.ValidationError, first_contact.name):
			ensure_contact_link(second_contact.name, "Donor", donor.name)

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
