from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import CallbackManager

from non_profit.non_profit import identity_lock


def _database():
	return SimpleNamespace(
		db_type="postgres",
		sql=Mock(),
		close=Mock(),
		rollback=Mock(),
		before_commit=CallbackManager(),
		after_commit=CallbackManager(),
		after_rollback=CallbackManager(),
	)


class TestPublicIdentityLock(UnitTestCase):
	def test_normalized_email_lock_is_hashed_reentrant_and_transaction_scoped(self) -> None:
		lock = Mock()
		lock.acquire.return_value = True
		lock.reacquire.return_value = True
		cache = SimpleNamespace(make_key=lambda key: key, lock=Mock(return_value=lock))
		database = _database()
		local = SimpleNamespace()
		thread = Mock()
		with (
			patch("non_profit.non_profit.identity_lock.frappe.cache", cache),
			patch("non_profit.non_profit.identity_lock.frappe.local", local),
			patch("non_profit.non_profit.identity_lock.Thread", return_value=thread),
			patch(
				"non_profit.non_profit.identity_lock.frappe.db",
				database,
			),
		):
			self.assertEqual(
				identity_lock.acquire_public_email_identity_lock(" Member@Example.org "),
				"member@example.org",
			)
			identity_lock.acquire_public_email_identity_lock("member@example.org")

		lock_key = cache.lock.call_args.args[0]
		self.assertTrue(lock_key.startswith("identity-lock:v1:"))
		self.assertNotIn("member@example.org", lock_key)
		self.assertFalse(cache.lock.call_args.kwargs["thread_local"])
		lock.acquire.assert_called_once_with()
		thread.start.assert_called_once_with()
		self.assertEqual(len(database.before_commit._functions), 1)
		self.assertEqual(len(database.after_commit._functions), 1)
		self.assertEqual(len(database.after_rollback._functions), 1)
		self.assertIn(lock_key, local.identity_lock_v1_registry.locks)

		# Mirror Frappe commit resetting rollback callbacks before before_commit.
		database.after_rollback.reset()
		with (
			patch("non_profit.non_profit.identity_lock.frappe.local", local),
			patch("non_profit.non_profit.identity_lock.frappe.db", database),
		):
			database.before_commit.run()
			self.assertEqual(len(database.after_rollback._functions), 1)
			database.after_commit.run()

		lock.reacquire.assert_called_once_with()
		lock.release.assert_called_once_with()
		self.assertFalse(hasattr(local, identity_lock.IDENTITY_LOCK_REGISTRY_ATTR))
		self.assertFalse(hasattr(local, identity_lock.IDENTITY_LOCK_AFTER_COMMIT_ATTR))

	def test_frappe_callback_reset_then_before_commit_failure_releases_on_rollback(self) -> None:
		lock = Mock(acquire=Mock(return_value=True), reacquire=Mock(return_value=True))
		cache = SimpleNamespace(make_key=lambda key: key, lock=Mock(return_value=lock))
		database = _database()
		database.before_commit.add(Mock(side_effect=RuntimeError("later before_commit failed")))
		local = SimpleNamespace()
		with (
			patch("non_profit.non_profit.identity_lock.frappe.cache", cache),
			patch("non_profit.non_profit.identity_lock.frappe.local", local),
			patch("non_profit.non_profit.identity_lock.frappe.db", database),
			patch("non_profit.non_profit.identity_lock.Thread", return_value=Mock()),
		):
			identity_lock.acquire_public_email_identity_lock("failure@example.org")
			database.after_rollback.reset()
			with self.assertRaisesRegex(RuntimeError, "later before_commit failed"):
				database.before_commit.run()
			database.after_rollback.run()

		lock.release.assert_called_once_with()
		self.assertFalse(hasattr(local, identity_lock.IDENTITY_LOCK_REGISTRY_ATTR))

	def test_terminal_cleanup_covers_sql_commit_failure_after_before_commit(self) -> None:
		lock = Mock(acquire=Mock(return_value=True), reacquire=Mock(return_value=True))
		cache = SimpleNamespace(make_key=lambda key: key, lock=Mock(return_value=lock))
		database = _database()
		local = SimpleNamespace()
		with (
			patch("non_profit.non_profit.identity_lock.frappe.cache", cache),
			patch("non_profit.non_profit.identity_lock.frappe.local", local),
			patch("non_profit.non_profit.identity_lock.frappe.db", database),
			patch("non_profit.non_profit.identity_lock.Thread", return_value=Mock()),
		):
			identity_lock.acquire_public_email_identity_lock("commit-failure@example.org")
			database.after_rollback.reset()
			database.before_commit.run()
			database.rollback.side_effect = database.after_rollback.run
			identity_lock.cleanup_identity_locks_after_job()

		lock.release.assert_called_once_with()
		database.close.assert_not_called()
		self.assertFalse(hasattr(local, identity_lock.IDENTITY_LOCK_REGISTRY_ATTR))

	def test_terminal_cleanup_hooks_are_registered(self) -> None:
		from non_profit import hooks

		self.assertIn(
			"non_profit.non_profit.identity_lock.cleanup_identity_locks_after_request",
			hooks.after_request,
		)
		self.assertIn(
			"non_profit.non_profit.identity_lock.cleanup_identity_locks_after_job",
			hooks.after_job,
		)

	def test_registry_renews_lease_until_release(self) -> None:
		lock = Mock()
		lock.reacquire.return_value = True
		with patch("non_profit.non_profit.identity_lock.Thread"):
			registry = identity_lock._IdentityLockRegistry()
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
			registry = identity_lock._IdentityLockRegistry()
		registry.add("key", lock)

		with (
			patch("non_profit.non_profit.identity_lock.frappe.db", _database()),
			self.assertRaisesRegex(frappe.ValidationError, "Identity serialization expired"),
		):
			registry.ensure_current()

		lock.release.assert_called_once_with()

	def test_commit_fails_closed_after_bounded_hold_period(self) -> None:
		lock = Mock()
		with (
			patch("non_profit.non_profit.identity_lock.Thread"),
			patch("non_profit.non_profit.identity_lock.monotonic", return_value=0),
		):
			registry = identity_lock._IdentityLockRegistry()
		registry.add("key", lock)

		with (
			patch(
				"non_profit.non_profit.identity_lock.monotonic",
				return_value=identity_lock.IDENTITY_LOCK_MAX_HOLD_SECONDS,
			),
			patch("non_profit.non_profit.identity_lock.frappe.db", _database()),
			self.assertRaisesRegex(frappe.ValidationError, "Identity serialization expired"),
		):
			registry.ensure_current()

		lock.reacquire.assert_not_called()
		lock.release.assert_called_once_with()
