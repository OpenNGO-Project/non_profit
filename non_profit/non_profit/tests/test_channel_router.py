import frappe
from frappe.tests import IntegrationTestCase

from non_profit.non_profit.channel_launch import _validate_recipient_selection_source
from non_profit.non_profit.channel_router import (
	donor_channel_preference,
	get_transactional_channels,
	send_transactional,
)
from non_profit.non_profit.recipient_selection import (
	CHANNEL_FIELDS,
	get_channel_fields,
	validate_recipient_selection,
)

CHANNEL_HOOK = "non_profit_recipient_selection_channels"
ROUTER_HOOK = "non_profit_transactional_channels"


def _patch_hooks(hook_name, paths):
	from unittest.mock import patch

	# Only the hook under test is controlled; every other lookup (permission
	# query conditions, doc events, …) must resolve normally or code paths
	# that read rows break on the substitute value.
	real_get_hooks = frappe.get_hooks

	def fake_get_hooks(name=None, *args, **kwargs):
		if name == hook_name:
			return paths
		return real_get_hooks(name, *args, **kwargs)

	return patch.object(frappe, "get_hooks", side_effect=fake_get_hooks)


# ---- registry hook providers (dotted paths must be importable) ----


def messenger_channel_provider():
	return {"key": "messenger", "fieldname": "available_for_messenger", "label": "Messenger (WhatsApp)"}


def colliding_channel_provider():
	return {"key": "newsletter", "fieldname": "some_other_field", "label": "X"}


def decline_descriptor():
	return {
		"key": "messenger",
		"can_send": "non_profit.non_profit.tests.test_channel_router._decline",
		"send": "non_profit.non_profit.tests.test_channel_router._boom",
	}


def accept_descriptor():
	return {
		"key": "messenger",
		"can_send": "non_profit.non_profit.tests.test_channel_router._accept",
		"send": "non_profit.non_profit.tests.test_channel_router._handled",
	}


def raise_descriptor():
	return {
		"key": "messenger",
		"can_send": "non_profit.non_profit.tests.test_channel_router._accept",
		"send": "non_profit.non_profit.tests.test_channel_router._raise",
	}


class TestRecipientSelectionChannelRegistry(IntegrationTestCase):
	def test_builtin_registry_unchanged_without_hooks(self) -> None:
		"""The neutral registry must preserve the two built-ins exactly."""
		with _patch_hooks(CHANNEL_HOOK, []):
			fields = get_channel_fields()
		self.assertEqual(fields["newsletter"], "available_for_newsletter")
		self.assertEqual(fields["direct_mail"], "available_for_direct_mail")
		self.assertEqual(
			CHANNEL_FIELDS,
			{"newsletter": "available_for_newsletter", "direct_mail": "available_for_direct_mail"},
		)

	def test_hook_registered_channel_joins_registry(self) -> None:
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			fields = get_channel_fields()
		self.assertEqual(fields.get("messenger"), "available_for_messenger")
		self.assertEqual(fields["newsletter"], "available_for_newsletter")

	def test_hook_channel_collision_is_ignored(self) -> None:
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.colliding_channel_provider"]
		):
			fields = get_channel_fields()
		self.assertEqual(fields["newsletter"], "available_for_newsletter")

	def test_validation_accepts_registered_channel(self) -> None:
		doc = frappe.new_doc("NPO Recipient Selection")
		doc.include_donors = 1
		doc.available_for_messenger = 1
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			validate_recipient_selection(doc)

	def test_launch_source_lists_registered_channel(self) -> None:
		selection = frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": "Registry Test Selection",
				"enabled": 1,
				"available_for_direct_mail": 1,
				"include_contacts": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "NPO Recipient Selection", selection.name, ignore_permissions=True, force=True
		)

		# Both built-in availability flags default to 1 on fresh selections.
		descriptor = _validate_recipient_selection_source(selection.name)
		self.assertEqual(descriptor["available_channels"], ["newsletter", "direct_mail"])

		# Registry patch does not change which flags the selection actually set.
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			descriptor = _validate_recipient_selection_source(selection.name)
		self.assertEqual(descriptor["available_channels"], ["newsletter", "direct_mail"])

	def test_launch_source_messenger_channel_when_field_exists(self) -> None:
		"""With the custom field present, the registered channel is listed."""
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		create_custom_fields(
			{
				"NPO Recipient Selection": [
					{
						"fieldname": "available_for_messenger",
						"label": "Available for WhatsApp",
						"fieldtype": "Check",
						"insert_after": "available_for_direct_mail",
					}
				]
			},
			update=True,
		)
		selection = frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": "Registry WhatsApp Selection",
				"enabled": 1,
				"available_for_direct_mail": 1,
				"available_for_messenger": 1,
				"include_contacts": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "NPO Recipient Selection", selection.name, ignore_permissions=True, force=True
		)
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			descriptor = _validate_recipient_selection_source(selection.name)
		self.assertEqual(set(descriptor["available_channels"]), {"newsletter", "direct_mail", "messenger"})

	def test_rows_readable_for_registered_channel(self) -> None:
		"""Gating a read on a registered channel must consult the resolved
		registry, not the built-in literals (a hardcoded lookup raised
		KeyError for every hook-registered channel)."""
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		from non_profit.non_profit.recipient_selection import get_recipient_selection_rows

		create_custom_fields(
			{
				"NPO Recipient Selection": [
					{
						"fieldname": "available_for_messenger",
						"label": "Available for Messenger (WhatsApp)",
						"fieldtype": "Check",
						"insert_after": "available_for_direct_mail",
					}
				]
			},
			update=True,
		)
		selection = frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": "Registry Rows Selection",
				"enabled": 1,
				"available_for_messenger": 1,
				"include_contacts": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "NPO Recipient Selection", selection.name, ignore_permissions=True, force=True
		)
		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			rows = get_recipient_selection_rows(selection, "messenger")
		self.assertIsInstance(rows, list)

	def test_rows_rejected_when_registered_channel_unavailable(self) -> None:
		"""The availability flag still gates: a selection not marked for the
		registered channel must be refused, not silently read."""
		selection = frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": "Registry Rows Denied",
				"enabled": 1,
				"available_for_messenger": 0,
				"include_contacts": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "NPO Recipient Selection", selection.name, ignore_permissions=True, force=True
		)
		from non_profit.non_profit.recipient_selection import get_recipient_selection_rows

		with _patch_hooks(
			CHANNEL_HOOK, ["non_profit.non_profit.tests.test_channel_router.messenger_channel_provider"]
		):
			with self.assertRaises(frappe.ValidationError):
				get_recipient_selection_rows(selection, "messenger")


class TestTransactionalChannelRouter(IntegrationTestCase):
	def _donor(self, name: str, delivery: str) -> str:
		frappe.db.delete("Donor", {"donor_name": name})
		donor = frappe.get_doc({"doctype": "Donor", "donor_name": name, "receipt_delivery": delivery})
		donor.donor_type = frappe.db.get_value("Donor Type", {}, "name") or ""
		donor.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Donor", donor.name, ignore_permissions=True, force=True)
		return donor.name

	def test_no_hooks_no_channels(self) -> None:
		with _patch_hooks(ROUTER_HOOK, []):
			self.assertEqual(get_transactional_channels(), [])

	def test_unhandled_preference_returns_false(self) -> None:
		with _patch_hooks(ROUTER_HOOK, []):
			self.assertFalse(send_transactional("donation_thank_you", frappe._dict(donor=None)))

	def test_declined_channel_returns_false(self) -> None:
		donor = self._donor("Router Decline", "Messenger")
		with _patch_hooks(
			ROUTER_HOOK, ["non_profit.non_profit.tests.test_channel_router.decline_descriptor"]
		):
			self.assertFalse(send_transactional("donation_thank_you", frappe._dict(donor=donor)))
		self.assertEqual(donor_channel_preference(donor), "Messenger")

	def test_accepted_channel_handles_send(self) -> None:
		donor = self._donor("Router Accept", "Messenger")
		doc = frappe._dict(donor=donor, name="X")
		with _patch_hooks(ROUTER_HOOK, ["non_profit.non_profit.tests.test_channel_router.accept_descriptor"]):
			self.assertTrue(send_transactional("tax_confirmation", doc, context={"a": 1}))

	def test_channel_exception_falls_back(self) -> None:
		donor = self._donor("Router Error", "Messenger")
		doc = frappe._dict(donor=donor)
		with _patch_hooks(ROUTER_HOOK, ["non_profit.non_profit.tests.test_channel_router.raise_descriptor"]):
			self.assertFalse(send_transactional("donation_thank_you", doc))

	def test_default_preference_never_routes(self) -> None:
		donor = self._donor("Router Email Default", "Email")
		self.assertEqual(donor_channel_preference(donor), "Email")
		with _patch_hooks(ROUTER_HOOK, ["non_profit.non_profit.tests.test_channel_router.accept_descriptor"]):
			self.assertFalse(send_transactional("donation_thank_you", frappe._dict(donor=donor)))


# ---- descriptor callables (dotted paths must be importable) ----


def _decline(flow, doc, profile):
	return False


def _boom(flow, doc, context):
	raise AssertionError("send must not run when can_send declines")


def _accept(flow, doc, profile):
	return True


def _handled(flow, doc, context):
	return {"handled": True}


def _raise(flow, doc, context):
	raise RuntimeError("channel exploded")
