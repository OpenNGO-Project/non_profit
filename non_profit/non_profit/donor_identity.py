from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import cstr, validate_email_address

from non_profit.non_profit.doctype.donor.donor import (
	donor_customer_share_identity,
	find_donor_customer_candidates,
	get_or_create_customer_for_donor,
)
from non_profit.non_profit.identity_lock import acquire_public_email_identity_lock, current_identity_read

ValuesProvider = Callable[[dict], dict | None]
ExistingDonorHandler = Callable[[object], None]
DonorInserter = Callable[[dict], object]


class IdentityCandidateDriftError(frappe.QueryDeadlockError, frappe.ValidationError):
	"""Retryable identity drift that remains safe at public request boundaries."""


def resolve_donor_customer_identity(
	*,
	donor_name: str,
	email: str,
	donor_type: str,
	ambiguous_email_policy: str = "latest",
	donor_values_provider: ValuesProvider | None = None,
	customer_values_provider: ValuesProvider | None = None,
	existing_donor_handler: ExistingDonorHandler | None = None,
	donor_inserter: DonorInserter | None = None,
) -> tuple[object, str]:
	"""Resolve one Donor/Customer identity with caller-owned presentation policy."""
	email = cstr(email).strip().lower()
	validate_email_address(email, throw=True)
	acquire_public_email_identity_lock(email)
	if ambiguous_email_policy not in ("latest", "reject"):
		raise ValueError(f"Unsupported ambiguous email policy: {ambiguous_email_policy}")
	with current_identity_read():
		donor_names, customer_names = find_donor_customer_candidates(email)
		snapshot_customer = frappe.db.get_value("Donor", donor_names[0], "customer") if donor_names else None
		current_candidates = find_donor_customer_candidates(email, for_update=True)
		if current_candidates != (donor_names, customer_names):
			raise IdentityCandidateDriftError(
				_("The donor identity changed while processing this request. Please retry.")
			)
		if ambiguous_email_policy == "reject":
			_reject_ambiguous_identity(email, donor_names, customer_names)

		if donor_names:
			donor = frappe.get_doc("Donor", donor_names[0], for_update=True)
			if cstr(donor.get("customer")).strip() != cstr(snapshot_customer).strip():
				raise IdentityCandidateDriftError(
					_("The donor identity changed while processing this request. Please retry.")
				)

	if donor_names:
		if existing_donor_handler:
			existing_donor_handler(donor)
	else:
		donor_type = cstr(donor_type).strip()
		if not donor_type or not frappe.db.exists("Donor Type", donor_type):
			frappe.throw(
				_("Donor setup is incomplete. Please contact support."),
				frappe.ValidationError,
			)
		values = {
			"doctype": "Donor",
			"donor_name": donor_name,
			"donor_type": donor_type,
		}
		if donor_values_provider and (provided := donor_values_provider(dict(values))):
			values.update(provided)
		donor = (
			donor_inserter(values)
			if donor_inserter
			else frappe.get_doc(values).insert(ignore_permissions=True)
		)

	customer = get_or_create_customer_for_donor(
		donor,
		email=email,
		customer_values_provider=customer_values_provider,
	)
	return donor, customer


def get_unambiguous_donor_by_email(email: str) -> object | None:
	"""Return one existing Donor without selecting among ambiguous identities."""
	email = cstr(email).strip().lower()
	validate_email_address(email, throw=True)
	acquire_public_email_identity_lock(email)
	with current_identity_read():
		donor_names, customer_names = find_donor_customer_candidates(email)
		current_candidates = find_donor_customer_candidates(email, for_update=True)
		if current_candidates != (donor_names, customer_names):
			raise IdentityCandidateDriftError(
				_("The donor identity changed while processing this request. Please retry.")
			)
		_reject_ambiguous_identity(email, donor_names, customer_names)
		return frappe.get_doc("Donor", donor_names[0], for_update=True) if donor_names else None


def _reject_ambiguous_identity(email: str, donor_names: list[str], customer_names: list[str]) -> None:
	donor_customer_conflict = bool(
		len(donor_names) == 1
		and len(customer_names) == 1
		and not donor_customer_share_identity(donor_names[0], customer_names[0], for_update=True)
	)
	if len(donor_names) <= 1 and len(customer_names) <= 1 and not donor_customer_conflict:
		return

	# Do not reveal identity multiplicity or write request metadata to Error Log.
	frappe.logger("non_profit").warning(
		"Ambiguous public donor identity: "
		f"email_sha256={sha256(email.encode()).hexdigest()} "
		f"donor_count={len(donor_names)} customer_count={len(customer_names)} "
		f"donor_customer_conflict={donor_customer_conflict}"
	)
	frappe.throw(
		_("We could not process your donation. Please contact us so we can help."),
		frappe.ValidationError,
	)
