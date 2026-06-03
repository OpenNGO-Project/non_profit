import frappe
from frappe import _
from frappe.utils import cstr

from non_profit.non_profit.doctype.chapter.chapter import join


def get_context(context):
    context.no_cache = True
    chapter_name = cstr(frappe.form_dict.get("name")).strip()
    if not chapter_name:
        frappe.throw(_("Chapter is required"), frappe.DoesNotExistError)

    chapter = frappe.get_doc("Chapter", chapter_name)
    if not chapter.published:
        chapter.check_permission("read")

    if frappe.session.user != "Guest":
        if frappe.session.user in [d.user for d in chapter.members if d.enabled == 1]:
            context.already_member = True
        else:
            if frappe.request.method == "GET":
                pass
            elif frappe.request.method == "POST":
                join(
                    chapter.name,
                    introduction=frappe.form_dict.get("introduction") or "",
                    website_url=frappe.form_dict.get("website_url") or "",
                )

    context.chapter = chapter
