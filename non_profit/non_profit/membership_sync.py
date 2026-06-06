"""Cross-app utilities for Membership lifecycle.

Provides:

* ``validate_no_overlap`` — on Membership.validate, reject saving when another
  active (New/Current) Membership for the same Member has overlapping
  ``from_date`` / ``to_date``. Perpetual memberships (to_date empty) are
  treated as "open-ended" — any date from ``from_date`` onwards overlaps.
* ``get_customer_for_membership`` / ``list_customer_memberships`` —
  navigation helpers used by downstream apps (miki_app etc.) that also want
  Customer-level views. Resolve via ``Membership.member → Member.customer``.

Membership no longer carries a direct Customer link — users create the
Member up-front (pointing at a Customer for B2B, standalone for B2C) and
then bind a Membership to that Member.
"""

from __future__ import annotations

import frappe
from frappe import _

_ACTIVE_STATUSES = {"New", "Current"}


def validate_no_overlap(doc, method: str | None = None) -> None:
    """Reject a second active Membership for the same Member overlapping in time.

    Cancelled/Expired rows are ignored. Perpetual (to_date empty) counts as
    open-ended — any new Membership starting on or after ``from_date`` is
    considered overlapping.
    """
    status = (doc.get("membership_status") or "").strip()
    if status not in _ACTIVE_STATUSES:
        return
    if not doc.get("member") or not doc.get("from_date"):
        return

    filters = {
        "name": ["!=", doc.name or ""],
        "member": doc.member,
        "membership_status": ["in", list(_ACTIVE_STATUSES)],
    }

    candidates = frappe.get_all(
        "Membership",
        filters=filters,
        fields=["name", "from_date", "to_date"],
    )

    for row in candidates:
        if _periods_overlap(
            doc.from_date,
            doc.get("to_date"),
            row.from_date,
            row.to_date,
        ):
            message = _(
                "An active Membership already exists for {0} overlapping "
                "{1} — {2} (existing: {3})"
            ).format(
                frappe.bold(doc.member),
                doc.from_date,
                doc.get("to_date") or "∞",
                row.name,
            )
            if getattr(doc.flags, "warn_on_membership_overlap", False):
                frappe.msgprint(message, title=_("Overlapping Membership"), indicator="orange")
                return
            frappe.throw(
                message,
                title=_("Overlapping Membership"),
            )


def _periods_overlap(a_from, a_to, b_from, b_to) -> bool:
    """Treat missing ``to`` as +∞ (perpetual membership)."""
    from frappe.utils import getdate

    a_from = getdate(a_from)
    b_from = getdate(b_from)
    a_to = getdate(a_to) if a_to else None
    b_to = getdate(b_to) if b_to else None

    # a ends before b starts?
    if a_to and a_to < b_from:
        return False
    # b ends before a starts?
    if b_to and b_to < a_from:
        return False
    return True


def get_customer_for_membership(membership) -> str | None:
    """Resolve the Customer linked to a Membership via ``member.customer``."""
    if isinstance(membership, str):
        membership = frappe.db.get_value(
            "Membership",
            membership,
            ["member"],
            as_dict=True,
        )
        if not membership:
            return None
    member = membership.get("member")
    if not member:
        return None
    return frappe.db.get_value("Member", member, "customer")


def list_customer_memberships(customer: str) -> list[dict]:
    """All Memberships whose Member links to this Customer, newest ``to_date`` first."""
    if not customer:
        return []
    members = frappe.get_all("Member", filters={"customer": customer}, pluck="name")
    if not members:
        return []
    return frappe.get_all(
        "Membership",
        filters={"member": ["in", members]},
        fields=[
            "name",
            "member",
            "membership_type",
            "membership_status",
            "from_date",
            "to_date",
            "amount",
            "subscription",
        ],
        order_by="to_date desc",
    )
