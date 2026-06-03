import frappe
from frappe import _
from frappe.utils import cstr


def get_context(context):
    context.no_cache = True
    chapter_name = cstr(frappe.form_dict.get("name")).strip()
    if not chapter_name:
        frappe.throw(_("Chapter is required"), frappe.DoesNotExistError)

    chapter = frappe.get_doc("Chapter", chapter_name)
    if not chapter.published:
        chapter.check_permission("read")

    context.member_deleted = any(
        member.user == frappe.session.user and member.enabled for member in chapter.members
    )
    context.chapter = chapter
