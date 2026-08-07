"""Shared campaign / Company eligibility gate for public donation surfaces.

H04 requires that a campaign offered to (or accepted from) an unauthenticated
donor belongs to the Company the Donation will be booked in. The check was
previously tended to be copied into separate guest entry points, which is a
drift risk on a security boundary. Public intake flows call this single helper.

Ownership is derived from the campaign's Cost Center, never from the campaign
name or from historical Donations.
"""

from __future__ import annotations

import frappe


def campaign_matches_company(campaign: str, company: str) -> bool:
	"""Return True when `campaign` may be booked against `company`.

	A campaign qualifies only when it is Active and linked to an enabled,
	non-group Cost Center owned by `company`. Anything else — unknown campaign,
	inactive campaign, missing/group/disabled Cost Center, or a Cost Center in a
	different Company — fails closed.
	"""
	if not campaign or not company:
		return False
	campaign_row = frappe.db.get_value(
		"Donation Campaign",
		campaign,
		["status", "cost_center"],
		as_dict=True,
	)
	if not campaign_row or campaign_row.status != "Active" or not campaign_row.cost_center:
		return False
	cost_center = frappe.db.get_value(
		"Cost Center",
		campaign_row.cost_center,
		["company", "is_group", "disabled"],
		as_dict=True,
	)
	return bool(
		cost_center
		and cost_center.company == company
		and not cost_center.is_group
		and not cost_center.disabled
	)
