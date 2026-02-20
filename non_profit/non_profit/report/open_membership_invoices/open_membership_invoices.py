import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        {
            "label": _("Invoice"),
            "fieldname": "invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 120,
        },
        {
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Due Date"),
            "fieldname": "due_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Amount"),
            "fieldname": "grand_total",
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "label": _("Outstanding"),
            "fieldname": "outstanding_amount",
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "label": _("Member"),
            "fieldname": "member",
            "fieldtype": "Link",
            "options": "Member",
            "width": 120,
        },
        {
            "label": _("Member Name"),
            "fieldname": "member_name",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": _("Primary Chapter"),
            "fieldname": "primary_chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 150,
        },
        {
            "label": _("Membership Type"),
            "fieldname": "membership_type",
            "fieldtype": "Link",
            "options": "Membership Type",
            "width": 120,
        },
    ]


def get_data(filters):
    membership_type = filters.get("membership_type") or "ÖDP Mitglied"
    chapter = filters.get("chapter")

    conditions = """
        si.docstatus = 1
        AND si.outstanding_amount > 0
        AND ms.membership_type = %s
    """

    params = [membership_type]

    if chapter:
        conditions += " AND m.primary_chapter = %s"
        params.append(chapter)

    data = frappe.db.sql(
        f"""
        SELECT
            si.name AS invoice,
            si.posting_date,
            si.due_date,
            si.grand_total,
            si.outstanding_amount,
            m.name AS member,
            m.member_name,
            m.primary_chapter,
            ms.membership_type
        FROM `tabSales Invoice` si
        INNER JOIN `tabMember` m ON m.customer = si.customer
        INNER JOIN `tabMembership` ms ON ms.member = m.name
        WHERE {conditions}
        AND ms.docstatus = 1
        ORDER BY si.due_date ASC
    """,
        tuple(params),
        as_dict=True,
    )

    return data
