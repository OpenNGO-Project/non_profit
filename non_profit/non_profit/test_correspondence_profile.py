from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from non_profit.non_profit.correspondence import (
	AMBIGUOUS_ADDRESS,
	MAX_SOURCE_REFERENCES,
	_fetch_rows,
	get_correspondence_profile,
	get_correspondence_profiles,
)
from non_profit.setup import make_custom_fields


class TestCorrespondenceProfile(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_contact_and_household_language_metadata(self) -> None:
		make_custom_fields()
		expected_contact_module = (
			"Good Connector" if "good_connector" in frappe.get_installed_apps() else "Non Profit"
		)

		contact_field = frappe.get_meta("Contact").get_field("preferred_language")
		self.assertEqual(contact_field.fieldtype, "Link")
		self.assertEqual(contact_field.options, "Language")
		self.assertFalse(contact_field.read_only)
		self.assertEqual(
			frappe.db.get_value(
				"Custom Field",
				{"dt": "Contact", "fieldname": "preferred_language"},
				"module",
			),
			expected_contact_module,
		)

		household_field = frappe.get_meta("Household").get_field("preferred_language")
		self.assertEqual(household_field.fieldtype, "Link")
		self.assertEqual(household_field.options, "Language")
		self.assertFalse(
			frappe.db.exists(
				"Custom Field",
				{"dt": "Household", "fieldname": "preferred_language"},
			)
		)

	def test_resolves_canonical_household_profile(self) -> None:
		self._ensure_language("fr", "French")
		secondary = self._contact("Anne", "Example")
		primary = self._contact("Zoe", "Example")
		household = frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": f"Example Household {frappe.generate_hash(length=8)}",
				"preferred_language": "fr",
				"members": [
					{"contact": secondary.name, "from_date": nowdate()},
					{"contact": primary.name, "from_date": nowdate(), "is_primary": 1},
				],
			}
		).insert(ignore_permissions=True)
		address = self._address("Household", household.name)

		profile = get_correspondence_profile("Household", household.name)

		self.assertEqual(profile["subject_type"], "Household")
		self.assertEqual(
			profile["canonical_subject"],
			{"doctype": "Household", "name": household.name},
		)
		self.assertEqual([person["contact"] for person in profile["people"]], [primary.name, secondary.name])
		self.assertEqual(profile["language"], "fr")
		self.assertEqual(
			profile["language_provenance"],
			{"doctype": "Household", "name": household.name, "fieldname": "preferred_language"},
		)
		self.assertEqual(profile["addressee"], household.household_name)
		self.assertEqual(profile["address"]["name"], address.name)
		self.assertEqual(profile["issue_codes"], [])

	def test_resolves_contact_only_profile(self) -> None:
		self._ensure_language("de", "German")
		contact = self._contact("Ada", "Example", preferred_language="de", identity_kind="")
		address = self._address("Contact", contact.name)
		modified_before = frappe.db.get_value("Contact", contact.name, "modified")

		profile = get_correspondence_profile("Contact", contact.name)

		self.assertEqual(profile["subject_type"], "Person")
		self.assertEqual(profile["canonical_subject"], {"doctype": "Contact", "name": contact.name})
		self.assertEqual(profile["people"][0]["first_name"], "Ada")
		self.assertEqual(profile["people"][0]["last_name"], "Example")
		self.assertEqual(profile["addressee"], "Ada Example")
		self.assertEqual(profile["language"], "de")
		self.assertEqual(
			profile["language_provenance"],
			{"doctype": "Contact", "name": contact.name, "fieldname": "preferred_language"},
		)
		self.assertEqual(profile["address"]["name"], address.name)
		self.assertEqual(profile["address_name"], address.name)
		self.assertFalse(frappe.db.get_value("Contact", contact.name, "npo_identity_kind"))
		self.assertEqual(frappe.db.get_value("Contact", contact.name, "modified"), modified_before)
		canonical_profile = get_correspondence_profile(
			canonical_subject_type="Contact",
			canonical_subject=contact.name,
			contacts=[contact.name],
			as_of=nowdate(),
		)
		self.assertEqual(canonical_profile["address_name"], address.name)
		self.assertEqual(
			canonical_profile["related_sources"],
			[{"doctype": "Contact", "name": contact.name}],
		)

	def test_permission_aware_profile_ignores_inaccessible_household(self) -> None:
		self._ensure_language("de", "German")
		contact = self._contact("Visible", "Person", preferred_language="de")
		household = frappe.get_doc(
			{
				"doctype": "Household",
				"household_name": f"Hidden Household {frappe.generate_hash(length=8)}",
				"members": [{"contact": contact.name, "from_date": nowdate()}],
			}
		).insert(ignore_permissions=True)
		self._address("Household", household.name)
		real_get_list = frappe.get_list

		def permission_filtered_get_list(doctype, *args, **kwargs):
			if doctype == "Household":
				return []
			return real_get_list(doctype, *args, **kwargs)

		with patch(
			"non_profit.non_profit.correspondence.frappe.get_list",
			side_effect=permission_filtered_get_list,
		):
			profile = get_correspondence_profile(
				"Contact",
				contact.name,
				respect_permissions=True,
			)

		self.assertIsNone(profile["household"])
		self.assertIsNone(profile["address"])

	def test_permission_aware_optional_fetch_skips_unreadable_doctype(self) -> None:
		with (
			patch("non_profit.non_profit.correspondence.frappe.has_permission", return_value=False),
			patch("non_profit.non_profit.correspondence.frappe.get_list") as get_list,
		):
			self.assertEqual(
				_fetch_rows(
					"Customer",
					{"CUSTOMER-HIDDEN"},
					["name"],
					respect_permissions=True,
				),
				{},
			)

		get_list.assert_not_called()

	def test_canonical_profile_uses_related_donor_language_and_address(self) -> None:
		self._ensure_language("fr", "French")
		contact = self._contact("Related", "Donor")
		donor = self._donor(contact.name, preferred_language="fr")
		address = self._address("Donor", donor.name)

		profile = get_correspondence_profiles(
			[
				{
					"canonical_subject_type": "Contact",
					"canonical_subject": contact.name,
					"contacts": [contact.name],
					"donors": [donor.name],
				}
			]
		)[0]

		self.assertEqual(profile["canonical_subject"], {"doctype": "Contact", "name": contact.name})
		self.assertEqual(profile["language"], "fr")
		self.assertEqual(
			profile["language_provenance"],
			{"doctype": "Donor", "name": donor.name, "fieldname": "preferred_language"},
		)
		self.assertEqual(profile["address_name"], address.name)
		self.assertIn(
			{"doctype": "Donor", "name": donor.name, "via": "Dynamic Link"},
			profile["address"]["provenance"],
		)

	def test_address_query_counts_only_exact_target_pairs(self) -> None:
		self._ensure_language("de", "German")
		contact = self._contact("Exact", "Pair", preferred_language="de")
		donor = self._donor(contact.name)
		target_address = self._address("Donor", donor.name)
		cross_product_address = self._address("Contact", contact.name)
		frappe.db.set_value(
			"Dynamic Link",
			cross_product_address.links[0].name,
			"link_name",
			donor.name,
			update_modified=False,
		)

		with patch("non_profit.non_profit.correspondence.MAX_RELATED_ROWS", 1):
			profile = get_correspondence_profiles(
				[
					{
						"canonical_subject_type": "Contact",
						"canonical_subject": contact.name,
						"donors": [donor.name],
					}
				]
			)[0]

		self.assertEqual(profile["address_name"], target_address.name)
		self.assertEqual(
			[candidate["name"] for candidate in profile["address_candidates"]], [target_address.name]
		)

	def test_batch_input_is_bounded_and_rejects_string_sequences(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "must be a list"):
			get_correspondence_profiles("Contact")
		with self.assertRaisesRegex(frappe.ValidationError, "Related Donor references must be a list"):
			get_correspondence_profiles(
				[
					{
						"canonical_subject_type": "Contact",
						"canonical_subject": "CONTACT-1",
						"donors": "DONOR-1",
					}
				]
			)

		def over_bound_references():
			for _index in range(MAX_SOURCE_REFERENCES + 1):
				yield ("Contact", "CONTACT-1")
			raise AssertionError("The bounded resolver consumed past its limit")

		with self.assertRaisesRegex(frappe.ValidationError, "At most 500"):
			get_correspondence_profiles(over_bound_references())

	def test_batch_keeps_tuple_and_mapping_source_compatibility(self) -> None:
		self._ensure_language("de", "German")
		contact = self._contact("Compatible", "Source", preferred_language="de")
		address = self._address("Contact", contact.name)

		profiles = get_correspondence_profiles(
			[
				("Contact", contact.name),
				{"doctype": "Contact", "name": contact.name},
				{"reference_doctype": "Contact", "reference_name": contact.name},
			]
		)

		self.assertEqual(len(profiles), 3)
		self.assertTrue(all(profile["address_name"] == address.name for profile in profiles))
		self.assertTrue(
			all(
				profile["canonical_subject"] == {"doctype": "Contact", "name": contact.name}
				for profile in profiles
			)
		)

	def test_rejects_generic_endpoint_as_person(self) -> None:
		contact = self._contact("Shared", "Mailbox", identity_kind="Generic Endpoint")

		with self.assertRaisesRegex(frappe.ValidationError, "Generic Endpoint"):
			get_correspondence_profile("Contact", contact.name)

	def test_reports_ambiguous_active_addresses(self) -> None:
		self._ensure_language("de", "German")
		contact = self._contact("Multiple", "Addresses", preferred_language="de")
		addresses = [self._address("Contact", contact.name) for _index in range(2)]

		profile = get_correspondence_profile("Contact", contact.name)

		self.assertIsNone(profile["address"])
		self.assertIn(AMBIGUOUS_ADDRESS, profile["issue_codes"])
		self.assertEqual(
			[candidate["name"] for candidate in profile["address_candidates"]],
			sorted(address.name for address in addresses),
		)

	def _contact(
		self,
		first_name: str,
		last_name: str,
		*,
		preferred_language: str | None = None,
		identity_kind: str = "Person",
	):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": last_name,
				"preferred_language": preferred_language,
				"npo_identity_kind": identity_kind,
			}
		).insert(ignore_permissions=True)

	def _address(self, link_doctype: str, link_name: str):
		unique = frappe.generate_hash(length=8)
		return frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Correspondence {unique}",
				"address_type": "Shipping",
				"address_line1": f"Main Street {unique}",
				"pincode": "8000",
				"city": "Zurich",
				"country": self._country(),
				"links": [{"link_doctype": link_doctype, "link_name": link_name}],
			}
		).insert(ignore_permissions=True)

	def _donor(self, contact: str, *, preferred_language: str | None = None):
		donor_type = f"Correspondence Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type}).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Related Donor {frappe.generate_hash(length=8)}",
				"donor_type": donor_type,
				"subject_type": "Individual",
				"contact": contact,
				"preferred_language": preferred_language,
			}
		).insert(ignore_permissions=True)

	def _country(self) -> str:
		return frappe.db.get_value("Country", {}, "name", order_by="name asc")

	def _ensure_language(self, code: str, language_name: str) -> None:
		if not frappe.db.exists("Language", code):
			frappe.get_doc(
				{"doctype": "Language", "language_code": code, "language_name": language_name}
			).insert(ignore_permissions=True)
