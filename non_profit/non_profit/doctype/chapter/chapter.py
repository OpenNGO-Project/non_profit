import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet
from frappe.website.website_generator import WebsiteGenerator


class Chapter(NestedSet, WebsiteGenerator):
    nsm_parent_field = "parent_chapter"
    nsm_oldparent_field = "old_parent"

    _website = frappe._dict(
        condition_field="published",
    )

    def get_context(self, context):
        context.no_cache = True
        context.show_sidebar = True
        context.parents = [
            dict(
                label=_("View All Chapters"), route="chapters", title=_("View Chapters")
            )
        ]

    def validate(self):
        if not self.route:
            self.route = "chapters/" + self.scrub(self.name)
        self.validate_parent_chapter_type()

    def validate_parent_chapter_type(self):
        if self.parent_chapter:
            parent_type = frappe.db.get_value(
                "Chapter", self.parent_chapter, "chapter_type"
            )
            if parent_type:
                parent_level = (
                    frappe.db.get_value("Chapter Type", parent_type, "level") or 0
                )
                if self.chapter_type:
                    my_level = (
                        frappe.db.get_value("Chapter Type", self.chapter_type, "level")
                        or 0
                    )
                    if my_level <= parent_level:
                        frappe.throw(
                            _(
                                "Parent chapter must have a higher hierarchy level than this chapter"
                            )
                        )

    def on_update(self):
        NestedSet.on_update(self)

    def enable(self):
        chapter = frappe.get_doc("Chapter", frappe.form_dict.name)
        chapter.append("members", dict(enable=self.value))
        chapter.save(ignore_permissions=1)
        frappe.db.commit()

    def get_child_chapters(self):
        return frappe.get_all(
            "Chapter",
            filters={"parent_chapter": self.name},
            fields=["name", "chapter_type"],
        )

    def get_all_descendants(self):
        if not self.lft or not self.rgt:
            return []
        return frappe.db.sql_list(
            "SELECT name FROM `tabChapter` WHERE lft > %s AND rgt < %s",
            (self.lft, self.rgt),
        )

    @frappe.whitelist()
    def get_member_count(self):
        return frappe.db.count("Member", filters={"primary_chapter": self.name})


def get_list_context(context):
    context.allow_guest = True
    context.no_cache = True
    context.show_sidebar = True
    context.title = _("All Chapters")
    context.no_breadcrumbs = True
    context.order_by = "creation desc"


@frappe.whitelist()
def leave(title, user_id, leave_reason):
    chapter = frappe.get_doc("Chapter", title)
    for member in chapter.members:
        if member.user == user_id:
            member.enabled = 0
            member.leave_reason = leave_reason
    chapter.save(ignore_permissions=1)
    frappe.db.commit()
    return _("Thank you for Feedback")


@frappe.whitelist()
def get_chapter_tree(chapter=None):
    if chapter:
        lft, rgt = frappe.db.get_value("Chapter", chapter, ["lft", "rgt"])
        chapters = frappe.get_all(
            "Chapter",
            filters={"lft": [">=", lft], "rgt": ["<=", rgt]},
            fields=["name", "parent_chapter", "chapter_type", "region"],
            order_by="lft",
        )
    else:
        chapters = frappe.get_all(
            "Chapter",
            fields=["name", "parent_chapter", "chapter_type", "region"],
            order_by="lft",
        )
    return chapters
