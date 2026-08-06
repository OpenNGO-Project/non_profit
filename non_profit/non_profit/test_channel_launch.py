"""Tests for the neutral multi-channel campaign launch service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from non_profit.non_profit.channel_launch import (
	_normalized_channel_keys,
	_required_text,
	create_channel_campaigns,
	get_launch_form,
	source_fingerprint,
)


def _fake_hooks(creators, sources=None):
	original_get_hooks = frappe.get_hooks

	def fake_get_hooks(hook=None, *args, **kwargs):
		if hook == "non_profit_audience_channel_creators":
			return creators
		if hook == "non_profit_audience_source_providers" and sources is not None:
			return sources
		return original_get_hooks(hook, *args, **kwargs)

	return patch.object(frappe, "get_hooks", side_effect=fake_get_hooks)


class TestChannelLaunchValidation(UnitTestCase):
	def test_unknown_source_provider_is_rejected(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Unsupported audience source"):
			create_channel_campaigns("carrier_pigeon", "ref", "Title", channels=["newsletter"])

	def test_at_least_one_channel_is_required(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "at least one campaign channel"):
			_normalized_channel_keys([])

	def test_campaign_title_is_required(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Campaign Title is required"):
			_required_text("  ", "Campaign Title is required.")

	def test_launch_field_allowlist_rejects_rich_html(self) -> None:
		from non_profit.non_profit.channel_launch import _normalized_field

		channel = {"key": "newsletter"}
		with self.assertRaisesRegex(frappe.ValidationError, "unsupported field"):
			_normalized_field(channel, {"fieldname": "evil", "fieldtype": "Text Editor"})

	def test_create_channel_campaigns_is_post_only(self) -> None:
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[create_channel_campaigns], ["POST"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[get_launch_form], ["GET"])

	def test_client_makes_required_fields_conditional_on_channel_selection(self) -> None:
		script = (Path(__file__).parents[1] / "public" / "js" / "channel_launch.js").read_text(
			encoding="utf-8"
		)
		self.assertIn('type: "GET"', script)
		self.assertIn("delete copy.reqd", script)
		self.assertIn("copy.mandatory_depends_on = `eval:${channelCondition}", script)


class TestChannelLaunchSelection(IntegrationTestCase):
	def _selection(self, name: str, *, newsletter: int = 1, direct_mail: int = 1):
		if frappe.db.exists("NPO Recipient Selection", name):
			return frappe.get_doc("NPO Recipient Selection", name)
		return frappe.get_doc(
			{
				"doctype": "NPO Recipient Selection",
				"selection_name": name,
				"enabled": 1,
				"available_for_newsletter": newsletter,
				"available_for_direct_mail": direct_mail,
				"include_contacts": 1,
			}
		).insert(ignore_permissions=True)

	def test_get_launch_form_filters_channels_by_selection_availability(self) -> None:
		selection = self._selection("_Launch Newsletter Only", newsletter=1, direct_mail=0)

		def newsletter_factory():
			return {
				"key": "newsletter",
				"label": "Newsletter",
				"launch_fields": "non_profit.non_profit.test_channel_launch.newsletter_fields",
				"create_campaign": "non_profit.non_profit.test_channel_launch.create_fake_campaign",
			}

		def direct_mail_factory():
			return {
				"key": "direct_mail",
				"label": "Direct Mail",
				"launch_fields": "non_profit.non_profit.test_channel_launch.direct_mail_fields",
				"create_campaign": "non_profit.non_profit.test_channel_launch.create_fake_campaign",
			}

		with _fake_hooks(
			[
				"non_profit.non_profit.test_channel_launch.newsletter_factory",
				"non_profit.non_profit.test_channel_launch.direct_mail_factory",
			]
		):
			# The factory callables must resolve; register module-level names.
			form = get_launch_form("npo_recipient_selection", selection.name)

		self.assertEqual([channel["key"] for channel in form["channels"]], ["newsletter"])
		self.assertEqual(form["source"]["source_label"], "_Launch Newsletter Only")

	def test_get_launch_form_omits_unavailable_channels(self) -> None:
		selection = self._selection("_Launch Authorized Channel")
		with _fake_hooks(
			[
				"non_profit.non_profit.test_channel_launch.newsletter_factory",
				"non_profit.non_profit.test_channel_launch.unavailable_factory",
			]
		):
			form = get_launch_form("npo_recipient_selection", selection.name)

		self.assertEqual([channel["key"] for channel in form["channels"]], ["newsletter"])

	def test_create_channel_campaigns_rechecks_channel_availability(self) -> None:
		selection = self._selection("_Launch Unauthorized Channel")
		with (
			_fake_hooks(["non_profit.non_profit.test_channel_launch.unavailable_factory"]),
			self.assertRaises(frappe.PermissionError),
		):
			create_channel_campaigns(
				"npo_recipient_selection",
				selection.name,
				"_Launch Unauthorized",
				channels=["unavailable"],
			)

	def test_create_channel_campaigns_dispatches_each_selected_creator(self) -> None:
		selection = self._selection("_Launch Both Channels")

		with _fake_hooks(
			[
				"non_profit.non_profit.test_channel_launch.newsletter_factory",
				"non_profit.non_profit.test_channel_launch.direct_mail_factory",
			]
		):
			result = create_channel_campaigns(
				"npo_recipient_selection",
				selection.name,
				"_Launch Combined",
				channels=["newsletter", "direct_mail"],
				channel_values={"newsletter": {"subject": "Hi"}, "direct_mail": {"company": "Co"}},
			)

		doctypes = sorted(campaign["doctype"] for campaign in result["campaigns"])
		self.assertEqual(doctypes, ["Good Direct Mail Campaign", "Good Newsletter Campaign"])
		newsletter = next(c for c in result["campaigns"] if c["doctype"] == "Good Newsletter Campaign")
		self.assertEqual(newsletter["name"], "GNL-2026-99999")

	def test_second_channel_failure_propagates_in_selection_order(self) -> None:
		selection = self._selection("_Launch Rollback")
		# The launcher runs creators sequentially inside the caller's request
		# transaction, so a later failure aborts the whole response. Verify the
		# ordering contract the rollback behavior relies on.
		calls: list[str] = []

		with (
			_fake_hooks(
				[
					"non_profit.non_profit.test_channel_launch.first_factory",
					"non_profit.non_profit.test_channel_launch.failing_factory",
				]
			),
			patch("non_profit.non_profit.test_channel_launch._TRACKED_CALLS", calls),
			self.assertRaisesRegex(frappe.ValidationError, "direct mail exploded"),
		):
			create_channel_campaigns(
				"npo_recipient_selection",
				selection.name,
				"_Launch Rollback Title",
				channels=["first", "failing"],
			)
		self.assertEqual(calls, ["first"])

	def test_required_source_transform_runs_before_requested_channels(self) -> None:
		calls: list[str] = []
		with (
			_fake_hooks(
				[
					"non_profit.non_profit.test_channel_launch.first_factory",
					"non_profit.non_profit.test_channel_launch.direct_mail_factory",
					"non_profit.non_profit.test_channel_launch.snapshot_factory",
				],
				["non_profit.non_profit.test_channel_launch.fake_source_factory"],
			),
			patch("non_profit.non_profit.test_channel_launch._TRACKED_CALLS", calls),
			patch(
				"non_profit.non_profit.test_channel_launch.fingerprint_fake_source",
				wraps=fingerprint_fake_source,
			) as fingerprint_source,
		):
			result = create_channel_campaigns(
				"fake_dynamic_source",
				"DYNAMIC-1",
				"_Launch Ordered",
				# A crafted client cannot run the real channel before the required
				# source transform merely by reversing the submitted key order.
				channels=["direct_mail", "first", "snapshot"],
			)

		self.assertEqual(calls, ["snapshot", "first"])
		self.assertEqual(
			[campaign["name"] for campaign in result["campaigns"]],
			["GDM-2026-99999", "GNL-TRACKED"],
		)
		self.assertEqual(fingerprint_source.call_count, 1)

	def test_required_source_transform_is_not_a_campaign_selection(self) -> None:
		with (
			_fake_hooks(
				["non_profit.non_profit.test_channel_launch.snapshot_factory"],
				["non_profit.non_profit.test_channel_launch.fake_source_factory"],
			),
			self.assertRaisesRegex(frappe.ValidationError, "at least one campaign channel"),
		):
			create_channel_campaigns(
				"fake_dynamic_source",
				"DYNAMIC-1",
				"_Launch Snapshot Only",
				channels=["snapshot"],
			)

	def test_source_fingerprint_changes_with_selection_configuration(self) -> None:
		selection = self._selection("_Launch Fingerprint")
		descriptor = {
			"source_provider": "npo_recipient_selection",
			"source_reference": selection.name,
		}
		first = source_fingerprint(descriptor)
		selection.available_for_newsletter = 0
		selection.save(ignore_permissions=True)
		second = source_fingerprint(descriptor)
		self.assertNotEqual(first, second)


# --- module-level factories used by the patched hook paths --------------------


def newsletter_fields():
	return [{"fieldname": "subject", "fieldtype": "Data", "label": "Subject", "reqd": 1}]


def direct_mail_fields():
	return [{"fieldname": "company", "fieldtype": "Data", "label": "Company", "reqd": 1}]


def newsletter_factory():
	return {
		"key": "newsletter",
		"label": "Newsletter",
		"launch_fields": "non_profit.non_profit.test_channel_launch.newsletter_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.create_newsletter",
	}


def direct_mail_factory():
	return {
		"key": "direct_mail",
		"label": "Direct Mail",
		"launch_fields": "non_profit.non_profit.test_channel_launch.direct_mail_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.create_direct_mail",
	}


def unavailable_factory():
	return {
		"key": "unavailable",
		"label": "Unavailable",
		"supports_source": "non_profit.non_profit.test_channel_launch.always_supports",
		"launch_fields": "non_profit.non_profit.test_channel_launch.direct_mail_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.create_direct_mail",
		"is_available": "non_profit.non_profit.test_channel_launch.never_available",
	}


def never_available(descriptor):
	del descriptor
	return False


def failing_factory():
	return {
		"key": "failing",
		"label": "Failing",
		"supports_source": "non_profit.non_profit.test_channel_launch.always_supports",
		"launch_fields": "non_profit.non_profit.test_channel_launch.direct_mail_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.create_failing",
	}


_TRACKED_CALLS: list[str] = []


def first_factory():
	return {
		"key": "first",
		"label": "First",
		"supports_source": "non_profit.non_profit.test_channel_launch.always_supports",
		"launch_fields": "non_profit.non_profit.test_channel_launch.direct_mail_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.track_first",
	}


def snapshot_factory():
	return {
		"key": "snapshot",
		"label": "Snapshot",
		"supports_source": "non_profit.non_profit.test_channel_launch.supports_dynamic_source",
		"launch_fields": "non_profit.non_profit.test_channel_launch.empty_fields",
		"create_campaign": "non_profit.non_profit.test_channel_launch.create_snapshot",
		"requires_selection": True,
	}


def fake_source_factory():
	return {
		"key": "fake_dynamic_source",
		"validate_source": "non_profit.non_profit.test_channel_launch.validate_fake_source",
		"fingerprint_source": "non_profit.non_profit.test_channel_launch.fingerprint_fake_source",
	}


def validate_fake_source(reference):
	return {
		"source_label": reference,
		"segment_type": "Dynamic",
		"available_channels": ["first", "direct_mail"],
	}


def fingerprint_fake_source(descriptor):
	return {"reference": descriptor["source_reference"], "segment_type": descriptor["segment_type"]}


def supports_dynamic_source(descriptor):
	return (
		descriptor.get("source_provider") == "fake_dynamic_source"
		and descriptor.get("segment_type") == "Dynamic"
	)


def empty_fields():
	return []


def always_supports(descriptor):
	return True


def track_first(*, descriptor, campaign_title, donation_campaign, source_fingerprint, values):
	if (
		descriptor.get("source_provider") == "fake_dynamic_source"
		and descriptor.get("segment_type") != "Static"
	):
		frappe.throw("source was not snapshotted")
	_TRACKED_CALLS.append("first")
	return {"doctype": "Good Newsletter Campaign", "name": "GNL-TRACKED", "label": campaign_title}


def create_snapshot(*, descriptor, campaign_title, donation_campaign, source_fingerprint, values):
	_TRACKED_CALLS.append("snapshot")
	descriptor["segment_type"] = "Static"
	return {
		"source": dict(descriptor),
		"campaign": {"doctype": "Fake Snapshot", "name": "STATIC-1", "label": campaign_title},
	}


def create_newsletter(*, descriptor, campaign_title, donation_campaign, source_fingerprint, values):
	if not values.get("subject"):
		frappe.throw("Subject is required")
	return {"doctype": "Good Newsletter Campaign", "name": "GNL-2026-99999", "label": campaign_title}


def create_direct_mail(*, descriptor, campaign_title, donation_campaign, source_fingerprint, values):
	return {"doctype": "Good Direct Mail Campaign", "name": "GDM-2026-99999", "label": campaign_title}


def create_failing(*, descriptor, campaign_title, donation_campaign, source_fingerprint, values):
	frappe.throw("direct mail exploded")
