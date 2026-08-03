"""Person-level Do-Not-Contact / Deceased suppression flags.

`NPO Contact Suppression` records that a person — identified by canonical
Contact, the shared person identity of this suite — must not be contacted at
all (scope `Do Not Contact`) or is deceased (scope `Deceased`). The doctype is
channel-neutral enrichment data: consuming campaign apps read it through
:func:`active_suppressed_contacts` as one ADDITIONAL exclusion reason inside
their own eligibility pipelines. It never replaces a channel's authoritative
consent or suppression machinery (email suppression, postal suppressions,
core unsubscribes), and this public app neither imports nor references those
private consumers.
"""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe.utils import cstr

SUPPRESSION_DOCTYPE = "NPO Contact Suppression"
#: Maximum Contact names per IN-clause chunk, so bulk eligibility checks from
#: consuming apps (up to 50,000 postal candidates) stay bounded per statement.
CONTACT_CHUNK_SIZE = 1_000


def active_suppressed_contacts(contact_names: Iterable[str]) -> set[str]:
	"""Return the subset of ``contact_names`` with an active contact suppression.

	Trusted server-side read for channel eligibility pipelines: any active row,
	whether `Do Not Contact` or `Deceased`, marks the person as not
	contactable. Callers keep their own channel-specific suppression rules and
	surface this set only as an extra exclusion reason.
	"""
	names = sorted({cstr(name).strip() for name in contact_names if cstr(name).strip()})
	if not names:
		return set()
	suppressed: set[str] = set()
	for start in range(0, len(names), CONTACT_CHUNK_SIZE):
		chunk = names[start : start + CONTACT_CHUNK_SIZE]
		suppressed.update(
			frappe.get_all(
				SUPPRESSION_DOCTYPE,
				filters={"contact": ["in", chunk], "active": 1},
				pluck="contact",
				limit=0,
			)
		)
	return suppressed
