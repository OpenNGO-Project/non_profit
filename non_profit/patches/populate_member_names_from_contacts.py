import frappe


def execute():
    if not frappe.db.has_column("Member", "first_name"):
        return

    members = frappe.get_all("Member", fields=["name"])

    for member in members:
        contact = get_linked_contact("Member", member.name)
        if contact:
            first_name = contact.get("first_name")
            last_name = contact.get("last_name")

            if first_name or last_name:
                frappe.db.set_value(
                    "Member",
                    member.name,
                    {"first_name": first_name or "", "last_name": last_name or ""},
                    update_modified=False,
                )

    frappe.db.commit()


def get_linked_contact(link_doctype, link_name):
    contact = frappe.db.sql(
        """
		SELECT c.name, c.first_name, c.last_name, c.email_id
		FROM `tabContact` c
		INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name
		WHERE dl.link_doctype = %s
		AND dl.link_name = %s
		AND dl.parenttype = 'Contact'
		LIMIT 1
	""",
        (link_doctype, link_name),
        as_dict=True,
    )

    return contact[0] if contact else None
