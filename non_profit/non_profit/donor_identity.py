from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import cstr, validate_email_address

from non_profit.non_profit.doctype.donor.donor import (
	find_donor_customer_candidates,
	get_or_create_customer_for_donor,
)
from non_profit.non_profit.identity_lock import acquire_public_email_identity_lock

ValuesProvider = Callable[[dict], dict | None]
ExistingDonorHandler = Callable[[object], None]
DonorInserter = Callable[[dict], object]


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
	donor_names, customer_names = find_donor_customer_candidates(email)
	if ambiguous_email_policy == "reject" and (len(donor_names) > 1 or len(customer_names) > 1):
		frappe.throw(
			_(
				"Multiple donor or customer identities use email address {0}. "
				"Staff must resolve the identity first."
			).format(frappe.bold(email)),
			frappe.ValidationError,
		)

	if donor_names:
		donor = frappe.get_doc("Donor", donor_names[0])
		if existing_donor_handler:
			existing_donor_handler(donor)
	else:
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
