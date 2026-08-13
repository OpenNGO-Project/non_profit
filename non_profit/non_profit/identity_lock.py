from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, validate_email_address

IDENTITY_LOCK_LEASE_SECONDS = 300
IDENTITY_LOCK_RENEWAL_INTERVAL_SECONDS = 120
IDENTITY_LOCK_MAX_HOLD_SECONDS = 1800
PUBLIC_EMAIL_IDENTITY_TYPE = "Contact Email"
IDENTITY_LOCK_REGISTRY_ATTR = "identity_lock_v1_registry"
IDENTITY_LOCK_AFTER_COMMIT_ATTR = "identity_lock_v1_after_commit"
LOGGER = logging.getLogger(__name__)


class _IdentityLockRegistry:
	"""Renew all identity locks owned by one transaction."""

	def __init__(self) -> None:
		self.locks: dict[object, Any] = {}
		self._acquired_at = monotonic()
		self._mutex = Lock()
		self._stop = Event()
		self._released = False
		self._lease_lost = False
		self._max_hold_reached = False
		self._started = False
		self._thread = Thread(
			target=self._renew_until_released,
			name="non-profit-identity-lock-renewal",
			daemon=True,
		)

	def contains(self, lock_key: object) -> bool:
		with self._mutex:
			return lock_key in self.locks

	def add(self, lock_key: object, lock: Any) -> None:
		with self._mutex:
			if self._released or self._lease_lost or self._max_hold_reached:
				raise RuntimeError("The identity lock registry is no longer active")
			self.locks[lock_key] = lock

	def start(self) -> None:
		with self._mutex:
			if self._started:
				return
			self._started = True
		self._thread.start()

	def ensure_current(self) -> None:
		"""Fail the transaction before commit if any lease is no longer owned."""
		# Frappe clears rollback callbacks before running before_commit. Re-arm
		# cleanup first so any later before_commit failure releases on rollback.
		try:
			_add_callback_first(frappe.db.after_rollback, self.release_all)
		except Exception:
			self.release_all()
			raise
		if monotonic() - self._acquired_at >= IDENTITY_LOCK_MAX_HOLD_SECONDS:
			with self._mutex:
				self._max_hold_reached = True
			self._abort_expired_transaction()

		with self._mutex:
			if not self.locks:
				return
			if self._released or self._lease_lost or self._max_hold_reached:
				current = False
			else:
				try:
					current = all(lock.reacquire() for lock in self.locks.values())
				except Exception:
					current = False
				if not current:
					self._lease_lost = True

		if not current:
			self._abort_expired_transaction()

	def release_all(self) -> None:
		self._stop.set()
		with self._mutex:
			if self._released:
				return
			self._released = True
			locks = list(self.locks.values())
			self.locks.clear()

		for lock in locks:
			try:
				lock.release()
			except Exception as error:
				_log_cleanup_failure("lock-release", error)
		self._clear_request_state()

	def _renew_until_released(self) -> None:
		while True:
			remaining = IDENTITY_LOCK_MAX_HOLD_SECONDS - (monotonic() - self._acquired_at)
			if remaining <= 0:
				with self._mutex:
					self._max_hold_reached = True
				return
			if self._stop.wait(min(IDENTITY_LOCK_RENEWAL_INTERVAL_SECONDS, remaining)):
				return
			if not self._renew_all():
				return

	def _renew_all(self) -> bool:
		with self._mutex:
			if self._released:
				return False
			try:
				for lock in self.locks.values():
					if not lock.reacquire():
						self._lease_lost = True
						return False
			except Exception:
				# A transient Redis failure can recover before the current TTL ends.
				return True
			return True

	def _abort_expired_transaction(self) -> None:
		self.release_all()
		frappe.throw(
			_("Identity serialization expired before the transaction completed. Please retry."),
			frappe.ValidationError,
		)

	def _clear_request_state(self) -> None:
		if getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None) is self:
			delattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR)

	def release_after_commit(self) -> None:
		try:
			self.release_all()
		finally:
			setattr(frappe.local, IDENTITY_LOCK_AFTER_COMMIT_ATTR, True)
			try:
				frappe.db.after_commit.add(_clear_after_commit_guard)
			except Exception as error:
				_log_cleanup_failure("after-commit-guard-clear-registration", error)


def acquire_public_email_identity_lock(email: str) -> str:
	"""Serialize one normalized public identity until commit or rollback."""
	email = cstr(email).strip().lower()
	validate_email_address(email, throw=True)
	acquire_identity_lock(
		PUBLIC_EMAIL_IDENTITY_TYPE,
		email,
		busy_message=_("Another public submission for this email address is still being processed."),
	)
	return email


def acquire_identity_lock(
	identity_type: str,
	identity_value: str,
	*,
	busy_message: str | None = None,
) -> None:
	"""Acquire a PII-safe, request-reentrant Redis lock for an identity."""
	if getattr(frappe.local, IDENTITY_LOCK_AFTER_COMMIT_ATTR, False):
		frappe.throw(
			_("Transaction-scoped identity operations cannot start after commit."),
			frappe.ValidationError,
		)
	normalized_type = _normalized_text(identity_type)
	normalized_value = _normalized_text(identity_value)
	if not normalized_type or not normalized_value:
		return

	digest = sha256(f"{normalized_type}\n{normalized_value}".encode()).hexdigest()
	lock_key = frappe.cache.make_key(f"identity-lock:v1:{digest}")
	registry = getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None)
	if registry is not None and registry.contains(lock_key):
		return

	lock = frappe.cache.lock(
		lock_key,
		timeout=IDENTITY_LOCK_LEASE_SECONDS,
		blocking_timeout=30,
		thread_local=False,
	)
	if not lock.acquire():
		frappe.throw(busy_message or _("Another operation for this identity is still being processed."))
	try:
		if registry is None:
			registry = _identity_lock_registry()
		registry.add(lock_key, lock)
		registry.start()
	except Exception:
		try:
			lock.release()
		except Exception as error:
			_log_cleanup_failure("lock-release", error)
		raise


@contextmanager
def current_identity_read() -> Iterator[None]:
	"""Read current committed identity rows while the Redis lock is owned."""
	registry = getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None)
	if registry is None or not registry.locks:
		frappe.throw(_("Identity serialization is required before a current identity read."))
	if (
		frappe.db.db_type != "mariadb"
		or getattr(frappe.local, "non_profit_snapshot_isolation_supported", None) is False
	):
		yield
		return

	state = getattr(frappe.local, "non_profit_current_read_mode", None)
	if state is not None:
		state.depth += 1
		try:
			yield
		finally:
			state.depth -= 1
		return

	try:
		enabled = cstr(frappe.db.sql("SELECT @@SESSION.innodb_snapshot_isolation")[0][0]).upper() in (
			"1",
			"ON",
		)
	except Exception as error:
		if error.args and error.args[0] == 1193:
			frappe.local.non_profit_snapshot_isolation_supported = False
			yield
			return
		raise

	if enabled:
		frappe.db.sql("SET SESSION innodb_snapshot_isolation = OFF")
	state = frappe._dict(depth=1, restore=enabled)
	frappe.local.non_profit_current_read_mode = state
	try:
		yield
	finally:
		state.depth -= 1
		if state.depth == 0:
			delattr(frappe.local, "non_profit_current_read_mode")
			if state.restore:
				try:
					frappe.db.sql("SET SESSION innodb_snapshot_isolation = ON")
				except Exception:
					try:
						frappe.db.close()
					except Exception as close_error:
						_log_cleanup_failure("snapshot-session-close", close_error)
					raise


def _identity_lock_registry() -> _IdentityLockRegistry:
	registry = getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None)
	if registry is not None:
		return registry

	registry = _IdentityLockRegistry()
	setattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, registry)
	try:
		_add_callback_first(frappe.db.before_commit, registry.ensure_current)
		_add_callback_first(frappe.db.after_commit, registry.release_after_commit)
		_add_callback_first(frappe.db.after_rollback, registry.release_all)
	except Exception:
		registry.release_all()
		raise
	return registry


def cleanup_identity_locks_after_request(*, response=None, request=None) -> None:
	"""Request-final safety net for failed commit/rollback callback chains."""
	try:
		_cleanup_stranded_identity_registry()
	finally:
		_clear_after_commit_guard()


def cleanup_identity_locks_after_job(*, method=None, kwargs=None, result=None) -> None:
	"""Job-final safety net for failed commit/rollback callback chains."""
	try:
		_cleanup_stranded_identity_registry()
	finally:
		_clear_after_commit_guard()


def _clear_after_commit_guard() -> None:
	if hasattr(frappe.local, IDENTITY_LOCK_AFTER_COMMIT_ATTR):
		delattr(frappe.local, IDENTITY_LOCK_AFTER_COMMIT_ATTR)


def _cleanup_stranded_identity_registry() -> None:
	registry = getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None)
	if registry is None:
		return
	try:
		frappe.db.rollback()
	except Exception as rollback_error:
		_log_cleanup_failure("terminal-rollback", rollback_error)
		if getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None) is registry:
			try:
				frappe.db.close()
			except Exception as close_error:
				_log_cleanup_failure("terminal-session-close", close_error)
	finally:
		if getattr(frappe.local, IDENTITY_LOCK_REGISTRY_ATTR, None) is registry:
			registry.release_all()


def _add_callback_first(callback_manager: Any, callback: Any) -> None:
	"""Put critical cleanup before ordinary callbacks on Frappe v16."""
	functions = getattr(callback_manager, "_functions", None)
	if functions is None:
		callback_manager.add(callback)
	else:
		functions.appendleft(callback)


def _log_cleanup_failure(action: str, error: Exception) -> None:
	exception_type = type(error).__name__[:80]
	try:
		frappe.logger("non_profit.identity_lock", allow_site=True).error(
			"Identity lock cleanup failed: action=%s exception=%s",
			action[:40],
			exception_type,
		)
	except Exception:
		try:
			LOGGER.error(
				"Identity lock cleanup failed: action=%s exception=%s",
				action[:40],
				exception_type,
			)
		except Exception:
			pass


def _normalized_text(value: object) -> str:
	return " ".join(cstr(value).split()).casefold()
