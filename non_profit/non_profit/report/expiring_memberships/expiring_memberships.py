# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from calendar import monthrange
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        _("Membership Type") + ":Link/Membership Type:100",
        _("Membership ID") + ":Link/Membership:140",
        _("Member ID") + ":Link/Member:140",
        _("Member Name") + ":Data:140",
        _("Email") + ":Data:140",
        _("Expiring On") + ":Date:120",
    ]


def get_data(filters):
    start, end = _month_bounds(filters)
    latest_by_member = {}
    memberships = frappe.get_all(
        "Membership",
        filters={"to_date": ["is", "set"]},
        fields=["name", "member", "membership_type", "membership_status", "to_date"],
        order_by="member asc, to_date desc, name desc",
    )
    for membership in memberships:
        if not membership.member or membership.member in latest_by_member:
            continue
        if membership.membership_status == "Cancelled":
            continue
        latest_by_member[membership.member] = membership

    expiring_memberships = [
        membership
        for membership in latest_by_member.values()
        if membership.to_date and start <= getdate(membership.to_date) <= end
    ]
    if not expiring_memberships:
        return []

    member_names = [membership.member for membership in expiring_memberships]
    members_by_name = {
        member.name: member
        for member in frappe.get_all(
            "Member",
            filters={"name": ["in", member_names]},
            fields=["name", "member_name", "email_id"],
        )
    }
    rows = []
    for membership in expiring_memberships:
        member = members_by_name.get(membership.member)
        if not member:
            continue
        rows.append(
            [
                membership.membership_type,
                membership.name,
                member.name,
                member.member_name,
                member.email_id,
                membership.to_date,
            ]
        )
    return sorted(rows, key=lambda row: (row[5], row[3] or ""))


def _month_bounds(filters) -> tuple[date, date]:
    month = _coerce_month(filters.get("month"))
    year = _coerce_year(filters.get("fiscal_year") or filters.get("year"))
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _coerce_month(value) -> int:
    if cint(value):
        month = cint(value)
    else:
        month = MONTHS.get(cstr(value).strip().lower()[:3])
    if not month or month < 1 or month > 12:
        frappe.throw(_("Select a valid month."))
    return month


def _coerce_year(value) -> int:
    raw = cstr(value).strip()
    if raw.isdigit():
        return cint(raw)
    if raw and frappe.db.exists("Fiscal Year", raw):
        return getdate(frappe.db.get_value("Fiscal Year", raw, "year_start_date")).year
    frappe.throw(_("Select a valid fiscal year."))
