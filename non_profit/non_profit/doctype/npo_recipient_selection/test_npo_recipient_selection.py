from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, nowdate

from non_profit.non_profit.doctype.npo_recipient_selection.npo_recipient_selection import (
	NPORecipientSelection,
)
from non_profit.non_profit.recipient_selection import (
	MAX_SELECTION_SOURCE_ROWS,
	PROVIDER_KEY,
	_assert_source_row_limit,
	_candidate_email,
	_complete_neutral_salutation,
	_donor_canonical_subject,
	_filter_visible_canonical_rows,
	_member_canonical_subject,
	_permission_visible_row_map,
	_RecipientCandidate,
	evaluate_recipient_selection,
	get_recipient_selection_configuration,
	get_recipient_selection_rows,
	newsletter_audience_provider,
	newsletter_selection_members,
	newsletter_selection_sources,
	preview_recipient_selection,
)


class TestNPORecipientSelectionValidation(UnitTestCase):
	def test_requires_channel_source_and_member_active_date(self) -> None:
		selection = self._selection()
		selection.available_for_newsletter = 0
		selection.available_for_direct_mail = 0
		with self.assertRaisesRegex(frappe.ValidationError, "delivery channel"):
			selection.validate()

		selection.available_for_newsletter = 1
		with self.assertRaisesRegex(frappe.ValidationError, "recipient source"):
			selection.validate()

		selection.include_members = 1
		selection.membership_active_on = None
		with self.assertRaisesRegex(frappe.ValidationError, "Membership Active On"):
			selection.validate()

	def test_candidate_count_deduplicates_canonical_subjects(self) -> None:
		selection = self._selection()
		selection.include_donors = 1
		rows = [
			{
				"canonical_subject_type": "Contact",
				"canonical_subject": "CONTACT-1",
				"source_doctype": "Donor",
				"source_name": "DONOR-1",
			},
			{
				"canonical_subject_type": "Contact",
				"canonical_subject": "CONTACT-1",
				"source_doctype": "Member",
				"source_name": "MEMBER-1",
			},
		]
		with patch(
			"non_profit.non_profit.doctype.npo_recipient_selection.npo_recipient_selection.evaluate_recipient_selection",
			return_value=rows,
		):
			selection.validate()

		self.assertEqual(selection.candidate_count, 1)
		self.assertTrue(selection.last_evaluated_on)

	def test_source_permission_is_required_before_evaluation(self) -> None:
		selection = self._selection()
		selection.include_members = 1
		selection.membership_active_on = nowdate()
		with (
			patch(
				"non_profit.non_profit.recipient_selection.frappe.has_permission",
				side_effect=lambda doctype, _ptype: doctype != "Membership",
			),
			self.assertRaises(frappe.PermissionError),
		):
			get_recipient_selection_rows(selection, "newsletter")

	def test_newsletter_provider_contract(self) -> None:
		provider = newsletter_audience_provider()
		self.assertEqual(provider["key"], "npo_recipient_selection")
		self.assertIn("list_sources", provider)
		self.assertIn("get_members", provider)

	def test_neutral_salutations_are_identity_kind_and_blank_safe(self) -> None:
		organization_greetings = {
			"de": "Sehr geehrte Damen und Herren,",
			"fr": "Madame, Monsieur,",
			"it": "Gentili Signore e Signori,",
			"en": "Dear Sir or Madam,",
		}
		for language, greeting in organization_greetings.items():
			self.assertEqual(
				_complete_neutral_salutation("Example Organization", language, kind="organization"),
				greeting,
			)
		self.assertEqual(
			_complete_neutral_salutation("Example Organization", "unsupported", kind="organization"),
			organization_greetings["de"],
		)
		self.assertEqual(
			_complete_neutral_salutation("Ada Example", "en", kind="person"), "Dear Ada Example,"
		)
		self.assertEqual(_complete_neutral_salutation("", "en", kind="person"), "Dear")
		self.assertEqual(_complete_neutral_salutation("", "fr", kind="household"), "Bonjour")
		self.assertEqual(
			_complete_neutral_salutation("Ada Example", "unsupported", kind="person"),
			"Guten Tag Ada Example",
		)

	def test_source_rows_respect_row_level_visibility(self) -> None:
		selection = self._selection()
		selection.include_contacts = 1
		contact = frappe._dict(
			name="CONTACT-1",
			full_name="Visible only by raw query",
			first_name="Visible",
			last_name="Contact",
		)
		with (
			patch("non_profit.non_profit.recipient_selection.frappe.has_permission", return_value=True),
			patch(
				"non_profit.non_profit.recipient_selection.frappe.get_list",
				side_effect=[[contact], []],
			),
		):
			self.assertEqual(evaluate_recipient_selection(selection), [])

	def test_role_canonicalization_fails_closed_for_missing_person_contact(self) -> None:
		self.assertEqual(
			_member_canonical_subject(
				frappe._dict(subject_type="Individual", contact=None, customer="CUSTOMER-1")
			),
			("", ""),
		)
		self.assertEqual(
			_donor_canonical_subject(
				frappe._dict(
					subject_type="",
					contact=None,
					customer=None,
					subject_household="HOUSEHOLD-1",
				)
			),
			("Household", "HOUSEHOLD-1"),
		)
		self.assertEqual(
			_donor_canonical_subject(
				frappe._dict(
					subject_type="Anonymous",
					contact="CONTACT-STALE",
					customer="CUSTOMER-1",
					subject_household=None,
				)
			),
			("", ""),
		)
		self.assertEqual(
			_donor_canonical_subject(
				frappe._dict(
					subject_type="Organization",
					contact="CONTACT-STALE",
					customer="CUSTOMER-1",
					subject_household=None,
				)
			),
			("Customer", "CUSTOMER-1"),
		)

	def test_permission_invisible_related_identity_is_removed_from_source_row(self) -> None:
		row = {
			"canonical_subject_type": "Contact",
			"canonical_subject": "CONTACT-1",
			"contact": "CONTACT-1",
			"customer": "CUSTOMER-HIDDEN",
		}

		def get_list(doctype, **_kwargs):
			if doctype == "Contact":
				return [frappe._dict(name="CONTACT-1", npo_identity_kind="Person")]
			return []

		with (
			patch("non_profit.non_profit.recipient_selection.frappe.has_permission", return_value=True),
			patch(
				"non_profit.non_profit.recipient_selection.frappe.get_list",
				side_effect=get_list,
			),
		):
			filtered = _filter_visible_canonical_rows([row])

		self.assertEqual(filtered[0]["contact"], "CONTACT-1")
		self.assertIsNone(filtered[0]["customer"])

	def test_customer_email_is_not_attributed_to_unrelated_primary_contact(self) -> None:
		candidate = _RecipientCandidate("Customer", "CUSTOMER-1", "Example Org")
		profile = {"people": [{"contact": "CONTACT-1"}]}
		context = {
			"customers": {
				"CUSTOMER-1": frappe._dict(
					email_id="office@example.org",
					customer_primary_contact="CONTACT-1",
				)
			},
			"contacts": {
				"CONTACT-1": frappe._dict(
					email_id="person@example.org",
					unsubscribed=0,
					npo_identity_kind="Person",
				)
			},
		}

		self.assertEqual(_candidate_email(candidate, profile, context), ("office@example.org", ""))

	def test_customer_email_opt_out_uses_a_different_contact_fallback(self) -> None:
		candidate = _RecipientCandidate("Customer", "CUSTOMER-1", "Example Org")
		profile = {"people": [{"contact": "CONTACT-2"}]}
		context = {
			"customers": {
				"CUSTOMER-1": frappe._dict(
					email_id="office@example.org",
					customer_primary_contact="CONTACT-ENDPOINT",
				)
			},
			"contacts": {
				"CONTACT-ENDPOINT": frappe._dict(
					email_id="office@example.org",
					unsubscribed=1,
					npo_identity_kind="Generic Endpoint",
				),
				"CONTACT-2": frappe._dict(
					email_id="person@example.org",
					unsubscribed=0,
					npo_identity_kind="Person",
				),
			},
		}

		self.assertEqual(
			_candidate_email(candidate, profile, context),
			("person@example.org", "CONTACT-2"),
		)

	def test_customer_email_fails_closed_for_inaccessible_related_contact(self) -> None:
		candidate = _RecipientCandidate("Customer", "CUSTOMER-1", "Example Org")
		profile = {"people": [], "inaccessible_contacts": ["CONTACT-HIDDEN"]}
		context = {
			"customers": {
				"CUSTOMER-1": frappe._dict(
					email_id="office@example.org",
					customer_primary_contact=None,
				)
			},
			"contacts": {},
		}

		self.assertEqual(_candidate_email(candidate, profile, context), ("", ""))

	def test_permission_visible_rows_are_batched_without_truncation(self) -> None:
		names = {f"CONTACT-{index:04d}" for index in range(501)}

		def get_list(_doctype, *, filters, **_kwargs):
			return [frappe._dict(name=name) for name in filters["name"][1]]

		with (
			patch("non_profit.non_profit.recipient_selection.frappe.has_permission", return_value=True),
			patch(
				"non_profit.non_profit.recipient_selection.frappe.get_list",
				side_effect=get_list,
			) as get_list_mock,
		):
			rows = _permission_visible_row_map("Contact", names, ["name"])

		self.assertEqual(len(rows), 501)
		self.assertEqual(get_list_mock.call_count, 2)

	def test_permission_visible_rows_skip_unreadable_optional_doctype(self) -> None:
		with (
			patch("non_profit.non_profit.recipient_selection.frappe.has_permission", return_value=False),
			patch("non_profit.non_profit.recipient_selection.frappe.get_list") as get_list_mock,
		):
			self.assertEqual(_permission_visible_row_map("Customer", {"CUSTOMER-1"}, ["name"]), {})

		get_list_mock.assert_not_called()

	def test_source_row_limit_fails_closed(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "source-row limit"):
			_assert_source_row_limit([None] * (MAX_SELECTION_SOURCE_ROWS + 1))

	def test_preview_is_get_only_bounded_and_excludes_postal_values(self) -> None:
		selection = self._selection()
		rows = [
			{
				"canonical_subject_type": "Contact",
				"canonical_subject": f"CONTACT-{index:03d}",
				"label": f"Contact {index}",
				"source_doctype": "Contact",
				"source_name": f"CONTACT-{index:03d}",
			}
			for index in range(55)
		]

		def delivery_rows(candidates):
			for candidate in candidates:
				yield (
					candidate,
					{
						"address": {
							"address_line1": "Hidden Street 1",
							"pincode": "8000",
							"city": "Zurich",
							"country": "Switzerland",
						}
					},
					{"email": "", "language": ""},
				)

		with (
			patch(
				"non_profit.non_profit.recipient_selection._selection_document",
				return_value=selection,
			),
			patch(
				"non_profit.non_profit.recipient_selection.evaluate_recipient_selection",
				return_value=rows,
			),
			patch(
				"non_profit.non_profit.recipient_selection._candidate_delivery_rows",
				side_effect=delivery_rows,
			),
		):
			result = preview_recipient_selection("Selection")

		self.assertEqual(result["total"], 55)
		self.assertEqual(len(result["rows"]), 50)
		self.assertNotIn("address", result["rows"][0])
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func[preview_recipient_selection],
			["GET"],
		)

	def _selection(self) -> NPORecipientSelection:
		return NPORecipientSelection(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": "Validation Selection",
				"enabled": 1,
				"available_for_newsletter": 1,
				"available_for_direct_mail": 1,
			}
		)


class TestNPORecipientSelection(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)

	def test_member_and_donor_sources_union_by_canonical_contact(self) -> None:
		contact = self._contact("Union", f"Person {self.suffix}", f"union-{self.suffix}@example.com")
		membership_type = self._membership_type()
		donor_type = self._donor_type()

		member = frappe.get_doc(
			{
				"doctype": "Member",
				"member_name": f"Union Member {self.suffix}",
				"subject_type": "Individual",
				"contact": contact.name,
			}
		).insert(ignore_permissions=True)
		membership = frappe.get_doc(
			{
				"doctype": "Membership",
				"member": member.name,
				"membership_type": membership_type,
				"membership_status": "Current",
				"from_date": add_days(nowdate(), -30),
			}
		)
		membership.flags.keep_to_date_open = True
		membership.insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Union Donor {self.suffix}",
				"donor_type": donor_type,
				"subject_type": "Individual",
				"contact": contact.name,
			}
		).insert(ignore_permissions=True)

		selection = self._insert_selection(
			include_members=1,
			membership_type=membership_type,
			membership_status="Current",
			membership_active_on=nowdate(),
			include_donors=1,
			donor_type=donor_type,
		)
		rows = get_recipient_selection_rows(selection.name, "direct_mail")

		self.assertEqual(selection.candidate_count, 1)
		self.assertEqual([row["source_doctype"] for row in rows], ["Donor", "Member"])
		self.assertEqual({row["canonical_subject"] for row in rows}, {contact.name})
		self.assertEqual({row.get("donor") for row in rows if row.get("donor")}, {donor.name})
		self.assertEqual(
			{row.get("membership") for row in rows if row.get("membership")},
			{membership.name},
		)

	def test_newsletter_members_dedupe_email_and_exclude_unsubscribed_contacts(self) -> None:
		tag = f"recipient-selection-{self.suffix}"
		active_contacts = [
			self._contact("Alpha", self.suffix, f"Shared-{self.suffix}@example.com"),
			self._contact("Beta", self.suffix, f"shared-{self.suffix}@example.com"),
		]
		unsubscribed = self._contact(
			"Gamma",
			self.suffix,
			f"optout-{self.suffix}@example.com",
			unsubscribed=1,
		)
		for contact in (*active_contacts, unsubscribed):
			contact.add_tag(tag)

		selection = self._insert_selection(include_contacts=1, contact_tag=tag)
		members = newsletter_selection_members(selection.name)

		expected_contact = min(contact.name for contact in active_contacts)
		reachable = [row for row in members if row["email"]]
		self.assertEqual(selection.candidate_count, 3)
		self.assertEqual(len(reachable), 1)
		self.assertEqual(reachable[0]["contact"], expected_contact)
		self.assertEqual(reachable[0]["email"].casefold(), f"shared-{self.suffix}@example.com")
		self.assertTrue(reachable[0]["salutation"].startswith("Guten Tag "))
		# The opted-out candidate stays in the payload with an empty email so the
		# newsletter import can report it as skipped-without-email.
		self.assertEqual(len([row for row in members if not row["email"]]), 1)

	def test_organization_selection_uses_final_legal_entity_salutation(self) -> None:
		email = f"organization-selection-{self.suffix}@example.com"
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Selection Organization {self.suffix}",
				"customer_type": "Company",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"email_id": email,
				"language": "en",
				"npo_subject_type": "Organization",
			}
		).insert(ignore_permissions=True)
		donor_type = self._donor_type()
		frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": customer.customer_name,
				"donor_type": donor_type,
				"subject_type": "Organization",
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)
		selection = self._insert_selection(include_donors=1, donor_type=donor_type)

		members = newsletter_selection_members(selection.name)

		self.assertEqual(len(members), 1)
		self.assertEqual(members[0]["email"], email)
		self.assertEqual(members[0]["language"], "en")
		self.assertEqual(members[0]["salutation"], "Dear Sir or Madam,")
		self.assertNotIn(customer.customer_name, members[0]["salutation"])

	def test_newsletter_members_refuse_a_selection_without_the_newsletter_flag(self) -> None:
		tag = f"refused-selection-{self.suffix}"
		contact = self._contact("Delta", self.suffix, f"delta-{self.suffix}@example.com")
		contact.add_tag(tag)
		direct_mail_only = self._insert_selection(
			include_contacts=1,
			contact_tag=tag,
			available_for_newsletter=0,
			available_for_direct_mail=1,
		)
		disabled = self._insert_selection(
			selection_name=f"Refused Disabled {self.suffix}",
			include_contacts=1,
			contact_tag=tag,
			enabled=0,
		)

		with self.assertRaisesRegex(frappe.ValidationError, "not available for newsletter"):
			newsletter_selection_members(direct_mail_only.name)
		with self.assertRaisesRegex(frappe.ValidationError, "is disabled"):
			newsletter_selection_members(disabled.name)

	def test_newsletter_import_confirms_subscribers_and_reports_missing_email(self) -> None:
		if "good_newsletter" not in frappe.get_installed_apps():
			self.skipTest("good_newsletter is not installed on this site")
		from good_newsletter.api.audience import run_import

		tag = f"import-selection-{self.suffix}"
		reachable = [
			self._contact("Import One", self.suffix, f"import-one-{self.suffix}@example.com"),
			self._contact(
				"Import Two",
				self.suffix,
				f"import-two-{self.suffix}@example.com",
				preferred_language="fr",
			),
		]
		without_email = self._contact("Import Three", self.suffix, None)
		for contact in (*reachable, without_email):
			contact.add_tag(tag)

		selection = self._insert_selection(include_contacts=1, contact_tag=tag)
		audience = frappe.get_doc(
			{
				"doctype": "Good Newsletter Audience",
				"title": f"_GNL Selection Import {self.suffix}",
				"default_language": "de",
				"double_opt_in_required": 1,
			}
		).insert(ignore_permissions=True)

		totals = run_import(audience.name, PROVIDER_KEY, selection.name, 0, "Administrator")

		self.assertEqual(totals["imported"], 2)
		self.assertEqual(totals["skipped_no_email"], 1)
		subscribers = frappe.get_all(
			"Good Newsletter Subscriber",
			filters={"audience": audience.name},
			fields=["email", "status", "salutation", "language", "contact"],
			order_by="email asc",
		)
		self.assertEqual(len(subscribers), 2)
		self.assertEqual({row.status for row in subscribers}, {"Confirmed"})
		self.assertEqual({row.contact for row in subscribers}, {contact.name for contact in reachable})
		by_email = {row.email: row for row in subscribers}
		german = by_email[f"import-one-{self.suffix}@example.com"]
		french = by_email[f"import-two-{self.suffix}@example.com"]
		self.assertEqual(german.language, "de")
		self.assertTrue(german.salutation.startswith("Guten Tag "))
		self.assertEqual(french.language, "fr")
		self.assertTrue(french.salutation.startswith("Bonjour "))

	def test_provider_sources_require_enabled_newsletter_flag(self) -> None:
		tag = f"provider-selection-{self.suffix}"
		frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
		available = self._insert_selection(include_contacts=1, contact_tag=tag)
		direct_mail_only = self._insert_selection(
			selection_name=f"Direct Mail Only {self.suffix}",
			include_contacts=1,
			contact_tag=tag,
			available_for_newsletter=0,
			available_for_direct_mail=1,
		)
		disabled = self._insert_selection(
			selection_name=f"Disabled {self.suffix}",
			include_contacts=1,
			contact_tag=tag,
			enabled=0,
		)

		sources = {row["value"] for row in newsletter_selection_sources()}
		self.assertIn(available.name, sources)
		self.assertNotIn(direct_mail_only.name, sources)
		self.assertNotIn(disabled.name, sources)

	def test_name_loading_checks_selection_read_permission(self) -> None:
		tag = f"permission-selection-{self.suffix}"
		frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
		selection = self._insert_selection(include_contacts=1, contact_tag=tag)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"recipient-member-{self.suffix}@example.com",
				"first_name": "Recipient Member",
				"enabled": 1,
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": "Non Profit Member"}],
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=user.name)

		try:
			frappe.set_user(user.name)
			with self.assertRaises(frappe.PermissionError):
				get_recipient_selection_configuration(selection.name)
		finally:
			frappe.set_user("Administrator")

	def test_selection_name_cannot_change_after_insert(self) -> None:
		tag = f"immutable-name-{self.suffix}"
		frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
		selection = self._insert_selection(include_contacts=1, contact_tag=tag)
		selection.selection_name = f"Changed {self.suffix}"

		with self.assertRaises(frappe.ValidationError):
			selection.save()

	def _insert_selection(self, **values):
		selection_name = values.pop("selection_name", f"Recipient Selection {self.suffix}")
		return frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": selection_name,
				"enabled": 1,
				"available_for_newsletter": 1,
				"available_for_direct_mail": 1,
				**values,
			}
		).insert()

	def _contact(
		self,
		first_name: str,
		last_name: str,
		email: str | None,
		*,
		unsubscribed: int = 0,
		preferred_language: str = "de",
	):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": last_name,
				"npo_identity_kind": "Person",
				"preferred_language": preferred_language,
				"unsubscribed": unsubscribed,
				"email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
			}
		).insert(ignore_permissions=True)

	def _membership_type(self) -> str:
		name = f"Recipient Membership {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Membership Type",
				"membership_type": name,
				"amount": 1,
			}
		).insert(ignore_permissions=True)
		return name

	def _donor_type(self) -> str:
		name = f"Recipient Donor {self.suffix}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name
