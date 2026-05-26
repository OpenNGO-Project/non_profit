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
    return frappe.db.sql(
        """
		SELECT ms.membership_type, ms.name, member.name, member.member_name,
		       member.email_id, ms.to_date
		FROM `tabMember` member
		INNER JOIN (
			SELECT membership.member, MAX(membership.to_date) AS max_membership_date
			FROM `tabMembership` membership
			WHERE membership.to_date IS NOT NULL
			  AND membership.to_date != ''
			  AND COALESCE(membership.membership_status, '') != 'Cancelled'
			GROUP BY membership.member
		) latest
		  ON member.name = latest.member
		INNER JOIN `tabMembership` ms
		  ON ms.member = latest.member
		 AND ms.to_date = latest.max_membership_date
		WHERE ms.to_date BETWEEN %(start)s AND %(end)s
		ORDER BY ms.to_date ASC, member.member_name ASC
		""",
        {"start": start, "end": end},
    )


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
