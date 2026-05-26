# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import cstr
from frappe.website.website_generator import WebsiteGenerator


class Chapter(WebsiteGenerator):
    _website = frappe._dict(
        condition_field="published",
    )

    def get_context(self, context):
        context.no_cache = True
        context.show_sidebar = True
        context.parents = [
            dict(label="View All Chapters", route="chapters", title="View Chapters")
        ]

    def validate(self):
        if not self.route:  # pylint: disable=E0203
            self.route = "chapters/" + self.scrub(self.name)

    def enable(self):
        chapter = frappe.get_doc("Chapter", frappe.form_dict.name)
        chapter.check_permission("write")
        chapter.append("members", dict(enable=self.value))
        chapter.save()


def get_list_context(context):
    context.allow_guest = True
    context.no_cache = True
    context.show_sidebar = True
    context.title = "All Chapters"
    context.no_breadcrumbs = True
    context.order_by = "creation desc"


@frappe.whitelist()
def leave(title: str, user_id: str | None = None, leave_reason: str = "") -> str:
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)

    chapter = frappe.get_doc("Chapter", title)
    target_user = cstr(user_id or frappe.session.user).strip()
    if target_user != frappe.session.user:
        chapter.check_permission("write")
    elif not any(
        member.user == target_user and member.enabled for member in chapter.members
    ):
        frappe.throw(
            _("You are not an active member of this chapter."), frappe.PermissionError
        )

    updated = False
    for member in chapter.members:
        if member.user == target_user:
            member.enabled = 0
            member.leave_reason = leave_reason
            updated = True
    if not updated:
        frappe.throw(_("Chapter member not found."), frappe.DoesNotExistError)

    chapter.save(ignore_permissions=target_user == frappe.session.user)
    return "Thank you for Feedback"
