# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _

from non_profit.non_profit.doctype.member.member import get_member_email


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        _("Membership Type") + ":Link/Membership Type:100",
        _("Membership ID") + ":Link/Membership:140",
        _("Member ID") + ":Link/Member:140",
        _("Member Name") + ":Data:140",
        _("Email") + ":Data:140",
        _("Expiring On") + ":Date:120",
    ]


def get_data(filters):
    filters["month"] = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ].index(filters.month) + 1

    rows = frappe.db.sql(
        """
		select ms.membership_type,ms.name,m.name,m.member_name,ms.max_membership_date
		from `tabMember` m
		inner join (select name,membership_type,max(to_date) as max_membership_date,member
					from `tabMembership`
					where paid = 1
					group by member
					order by max_membership_date asc) ms
		on m.name = ms.member
		where month(max_membership_date) = %(month)s and year(max_membership_date) = %(year)s """,
        {"month": filters.get("month"), "year": filters.get("fiscal_year")},
    )

    for row in rows:
        row[4:4] = [get_member_email(row[2]) or ""]

    return rows
