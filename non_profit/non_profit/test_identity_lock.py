from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.identity_lock import (
	IDENTITY_LOCK_MAX_HOLD_SECONDS,
	_IdentityLockRegistry,
	acquire_public_email_identity_lock,
)


class TestPublicIdentityLock(UnitTestCase):
	def test_normalized_email_lock_is_hashed_reentrant_and_transaction_scoped(self) -> None:
		lock = Mock()
		lock.acquire.return_value = True
		lock.reacquire.return_value = True
		cache = SimpleNamespace(make_key=lambda key: key, lock=Mock(return_value=lock))
		before_commit = SimpleNamespace(add=Mock())
		after_commit = SimpleNamespace(add=Mock())
		after_rollback = SimpleNamespace(add=Mock())
		local = SimpleNamespace()
		thread = Mock()
		with (
			patch("non_profit.non_profit.identity_lock.frappe.cache", cache),
			patch("non_profit.non_profit.identity_lock.frappe.local", local),
			patch("non_profit.non_profit.identity_lock.Thread", return_value=thread),
			patch(
				"non_profit.non_profit.identity_lock.frappe.db",
				SimpleNamespace(
					before_commit=before_commit,
					after_commit=after_commit,
					after_rollback=after_rollback,
				),
			),
		):
			self.assertEqual(acquire_public_email_identity_lock(" Member@Example.org "), "member@example.org")
			acquire_public_email_identity_lock("member@example.org")

		lock_key = cache.lock.call_args.args[0]
		self.assertNotIn("member@example.org", lock_key)
		self.assertFalse(cache.lock.call_args.kwargs["thread_local"])
		lock.acquire.assert_called_once_with()
		thread.start.assert_called_once_with()
		before_commit.add.assert_called_once()
		after_commit.add.assert_called_once()
		after_rollback.add.assert_called_once()
		self.assertIn(lock_key, local.non_profit_identity_locks)

		with patch("non_profit.non_profit.identity_lock.frappe.local", local):
			before_commit.add.call_args.args[0]()
			after_commit.add.call_args.args[0]()
			after_rollback.add.call_args.args[0]()

		lock.reacquire.assert_called_once_with()
		lock.release.assert_called_once_with()
		self.assertFalse(hasattr(local, "non_profit_identity_locks"))

	def test_registry_renews_lease_until_release(self) -> None:
		lock = Mock()
		lock.reacquire.return_value = True
		with patch("non_profit.non_profit.identity_lock.Thread"):
			registry = _IdentityLockRegistry()
		registry.add("key", lock)

		with (
			patch.object(registry._stop, "wait", side_effect=[False, True]),
			patch("non_profit.non_profit.identity_lock.monotonic", return_value=registry._acquired_at),
		):
			registry._renew_until_released()

		lock.reacquire.assert_called_once_with()

	def test_commit_fails_closed_after_lease_is_lost(self) -> None:
		lock = Mock()
		lock.reacquire.return_value = False
		with patch("non_profit.non_profit.identity_lock.Thread"):
			registry = _IdentityLockRegistry()
		registry.add("key", lock)

		with self.assertRaisesRegex(frappe.ValidationError, "Identity serialization expired"):
			registry.ensure_current()

		lock.release.assert_called_once_with()

	def test_commit_fails_closed_after_bounded_hold_period(self) -> None:
		lock = Mock()
		with patch("non_profit.non_profit.identity_lock.Thread"):
			registry = _IdentityLockRegistry()
		registry.add("key", lock)

		with (
			patch(
				"non_profit.non_profit.identity_lock.monotonic",
				return_value=registry._acquired_at + IDENTITY_LOCK_MAX_HOLD_SECONDS,
			),
			self.assertRaisesRegex(frappe.ValidationError, "Identity serialization expired"),
		):
			registry.ensure_current()

		lock.reacquire.assert_not_called()
		lock.release.assert_called_once_with()
