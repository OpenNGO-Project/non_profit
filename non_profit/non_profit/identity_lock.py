from __future__ import annotations

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
			except Exception:
				frappe.log_error(title="Non Profit identity lock release failed")
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
		if getattr(frappe.local, "non_profit_identity_lock_registry", None) is self:
			delattr(frappe.local, "non_profit_identity_lock_registry")
		if getattr(frappe.local, "non_profit_identity_locks", None) is self.locks:
			delattr(frappe.local, "non_profit_identity_locks")


def acquire_public_email_identity_lock(email: str) -> str:
	"""Serialize one normalized public identity until commit or rollback."""
	email = cstr(email).strip().lower()
	validate_email_address(email, throw=True)
	acquire_identity_lock(
		"Individual",
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
	normalized_type = _normalized_text(identity_type)
	normalized_value = _normalized_text(identity_value)
	if not normalized_type or not normalized_value:
		return

	digest = sha256(f"{normalized_type}\n{normalized_value}".encode()).hexdigest()
	lock_key = frappe.cache.make_key(f"non-profit-identity:{digest}")
	registry = _identity_lock_registry()
	if registry.contains(lock_key):
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
		registry.add(lock_key, lock)
		registry.start()
	except Exception:
		try:
			lock.release()
		except Exception:
			frappe.log_error(title="Non Profit identity lock release failed")
		raise


def _identity_lock_registry() -> _IdentityLockRegistry:
	registry = getattr(frappe.local, "non_profit_identity_lock_registry", None)
	if registry is not None:
		return registry

	registry = _IdentityLockRegistry()
	frappe.local.non_profit_identity_lock_registry = registry
	frappe.local.non_profit_identity_locks = registry.locks
	try:
		frappe.db.before_commit.add(registry.ensure_current)
		frappe.db.after_commit.add(registry.release_all)
		frappe.db.after_rollback.add(registry.release_all)
	except Exception:
		registry.release_all()
		raise
	return registry


def _normalized_text(value: object) -> str:
	return " ".join(cstr(value).split()).casefold()
