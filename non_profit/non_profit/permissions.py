"""
Chapter-based permission system for hierarchical access control.

Uses Frappe's built-in User Permission system with a custom access_level field.
Users are granted access to chapters via User Permission records.
Access automatically cascades to all descendant chapters via NestedSet hierarchy.
"""

import frappe
from frappe import _


def get_member_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Members based on user's chapter access.

    A user can access a member if:
    1. The member's primary_chapter is in the user's accessible chapters
    2. The member has an active role in one of the user's accessible chapters
    """
    if user == "Administrator":
        return ""

    if "Non Profit Manager" in frappe.get_roles(user):
        return ""

    accessible_chapters = get_user_accessible_chapters(user)

    if not accessible_chapters:
        return "1=0"

    chapter_list = "', '".join([c.replace("'", "''") for c in accessible_chapters])

    return f"""
        (`tabMember`.`primary_chapter` IN ('{chapter_list}')
        OR EXISTS (
            SELECT 1 FROM `tabChapter Member Role` cr
            WHERE cr.parent = `tabMember`.`name`
            AND cr.chapter IN ('{chapter_list}')
            AND cr.is_active = 1
        ))
    """


def get_chapter_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Chapters based on user's chapter access.

    A user can access a chapter if it's in their accessible chapters list.
    """
    if user == "Administrator":
        return ""

    if "Non Profit Manager" in frappe.get_roles(user):
        return ""

    accessible_chapters = get_user_accessible_chapters(user)

    if not accessible_chapters:
        return "1=0"

    chapter_list = "', '".join([c.replace("'", "''") for c in accessible_chapters])

    return f"`tabChapter`.`name` IN ('{chapter_list}')"


def _get_base_conditions(user: str) -> tuple[str | None, str | None]:
    """
    Get base conditions for permission queries.

    Returns:
        Tuple of (chapter_list_sql, empty_condition):
        - (None, None): User has full access (Administrator or Non Profit Manager)
        - (None, "1=0"): User has no accessible chapters
        - (chapter_list, None): User has accessible chapters, use chapter_list in queries
    """
    if user == "Administrator":
        return None, None

    if "Non Profit Manager" in frappe.get_roles(user):
        return None, None

    accessible_chapters = get_user_accessible_chapters(user)

    if not accessible_chapters:
        return None, "1=0"

    chapter_list = "', '".join([c.replace("'", "''") for c in accessible_chapters])
    return chapter_list, None


def _get_member_chapter_subquery(table_alias: str = "m") -> str:
    """
    Generate a reusable subquery for checking if a member belongs to accessible chapters.

    Args:
        table_alias: The alias for the member table in the outer query.

    Returns:
        SQL subquery string (placeholder - chapter_list must be injected).
    """
    return f"""
        ({table_alias}.`primary_chapter` IN ('{{chapter_list}}')
        OR EXISTS (
            SELECT 1 FROM `tabChapter Member Role` cr
            WHERE cr.parent = {table_alias}.`name`
            AND cr.chapter IN ('{{chapter_list}}')
            AND cr.is_active = 1
        ))
    """


def get_membership_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Memberships based on user's chapter access.

    A user can access a membership if the member belongs to one of their accessible chapters.
    """
    chapter_list, empty_condition = _get_base_conditions(user)

    if empty_condition == "1=0":
        return "1=0"

    if chapter_list is None:
        return ""

    member_condition = _get_member_chapter_subquery("m").format(
        chapter_list=chapter_list
    )

    return f"""
        EXISTS (
            SELECT 1 FROM `tabMember` m
            WHERE m.name = `tabMembership`.`member`
            AND {member_condition}
        )
    """


def get_subscription_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Subscriptions based on user's chapter access.

    A user can access a subscription if:
    1. party_type is not 'Customer' (other party types pass through)
    2. party (Customer) is linked to a member in an accessible chapter
    3. subscription is linked to a Membership whose member is in an accessible chapter
    """
    chapter_list, empty_condition = _get_base_conditions(user)

    if empty_condition == "1=0":
        return "1=0"

    if chapter_list is None:
        return ""

    member_condition = _get_member_chapter_subquery("m").format(
        chapter_list=chapter_list
    )

    return f"""
        (`tabSubscription`.`party_type` != 'Customer'
        OR EXISTS (
            SELECT 1 FROM `tabMember` m
            WHERE m.customer = `tabSubscription`.`party`
            AND {member_condition}
        )
        OR EXISTS (
            SELECT 1 FROM `tabMembership` ms
            JOIN `tabMember` m ON m.name = ms.member
            WHERE ms.subscription = `tabSubscription`.`name`
            AND {member_condition}
        ))
    """


def get_sales_invoice_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Sales Invoices based on user's chapter access.

    A user can access a sales invoice if the customer is linked to a member
    in one of their accessible chapters.
    """
    chapter_list, empty_condition = _get_base_conditions(user)

    if empty_condition == "1=0":
        return "1=0"

    if chapter_list is None:
        return ""

    member_condition = _get_member_chapter_subquery("m").format(
        chapter_list=chapter_list
    )

    return f"""
        EXISTS (
            SELECT 1 FROM `tabMember` m
            WHERE m.customer = `tabSales Invoice`.`customer`
            AND {member_condition}
        )
    """


def get_contact_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Contacts based on user's chapter access.

    A user can access a contact if:
    1. The contact is directly linked to a member in an accessible chapter, OR
    2. The contact is linked to a customer that belongs to a member in an accessible chapter
    """
    chapter_list, empty_condition = _get_base_conditions(user)

    if empty_condition == "1=0":
        return "1=0"

    if chapter_list is None:
        return ""

    member_condition = _get_member_chapter_subquery("m").format(
        chapter_list=chapter_list
    )

    return f"""
        (
            EXISTS (
                SELECT 1 FROM `tabDynamic Link` dl
                JOIN `tabMember` m ON m.name = dl.link_name
                WHERE dl.parent = `tabContact`.`name`
                AND dl.parenttype = 'Contact'
                AND dl.link_doctype = 'Member'
                AND {member_condition}
            )
            OR EXISTS (
                SELECT 1 FROM `tabDynamic Link` dl
                JOIN `tabMember` m ON m.customer = dl.link_name
                WHERE dl.parent = `tabContact`.`name`
                AND dl.parenttype = 'Contact'
                AND dl.link_doctype = 'Customer'
                AND {member_condition}
            )
        )
    """


def get_address_query_condition(user: str) -> str:
    """
    Return SQL condition to filter Addresses based on user's chapter access.

    A user can access an address if:
    1. The address is directly linked to a member in an accessible chapter, OR
    2. The address is linked to a customer that belongs to a member in an accessible chapter
    """
    chapter_list, empty_condition = _get_base_conditions(user)

    if empty_condition == "1=0":
        return "1=0"

    if chapter_list is None:
        return ""

    member_condition = _get_member_chapter_subquery("m").format(
        chapter_list=chapter_list
    )

    return f"""
        (
            EXISTS (
                SELECT 1 FROM `tabDynamic Link` dl
                JOIN `tabMember` m ON m.name = dl.link_name
                WHERE dl.parent = `tabAddress`.`name`
                AND dl.parenttype = 'Address'
                AND dl.link_doctype = 'Member'
                AND {member_condition}
            )
            OR EXISTS (
                SELECT 1 FROM `tabDynamic Link` dl
                JOIN `tabMember` m ON m.customer = dl.link_name
                WHERE dl.parent = `tabAddress`.`name`
                AND dl.parenttype = 'Address'
                AND dl.link_doctype = 'Customer'
                AND {member_condition}
            )
        )
    """


def get_user_accessible_chapters(user: str) -> list[str]:
    """
    Get all chapters a user has access to.

    This includes:
    1. Directly assigned chapters via User Permission (allow="Chapter")
    2. All descendant chapters (automatic inheritance via NestedSet)

    The result is cached for performance.
    """
    if user == "Administrator":
        return frappe.get_all("Chapter", pluck="name", ignore_permissions=True)

    cache_key = f"accessible_chapters:{user}"
    cached = frappe.cache.get_value(cache_key)
    if cached is not None:
        return cached

    permissions = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Chapter"},
        fields=["for_value"],
        ignore_permissions=True,
    )

    chapters = set()

    for perm in permissions:
        chapters.add(perm.for_value)
        descendants = get_descendant_chapters(perm.for_value)
        chapters.update(descendants)

    result = list(chapters)

    frappe.cache.set_value(cache_key, result, expires_in_sec=300)

    return result


def get_descendant_chapters(chapter_name: str) -> list[str]:
    """
    Get all descendant chapters of a given chapter using NestedSet lft/rgt.

    Returns empty list if the chapter doesn't have lft/rgt values set.
    """
    chapter = frappe.db.get_value("Chapter", chapter_name, ["lft", "rgt"], as_dict=True)

    if not chapter or not chapter.lft or not chapter.rgt:
        return []

    return frappe.db.sql_list(
        "SELECT name FROM `tabChapter` WHERE lft > %s AND rgt < %s",
        (chapter.lft, chapter.rgt),
    )


def get_ancestor_chapters(chapter_name: str) -> list[str]:
    """
    Get all ancestor chapters of a given chapter using NestedSet lft/rgt.

    Returns list ordered from immediate parent to root.
    """
    chapter = frappe.db.get_value("Chapter", chapter_name, ["lft", "rgt"], as_dict=True)

    if not chapter or not chapter.lft or not chapter.rgt:
        return []

    return frappe.db.sql_list(
        "SELECT name FROM `tabChapter` WHERE lft < %s AND rgt > %s ORDER BY lft DESC",
        (chapter.lft, chapter.rgt),
    )


def clear_user_chapter_cache(doc, method=None):
    """
    Clear the cached accessible chapters for a user.

    Called via doc_events on User Permission.
    Only clears cache for Chapter-related permissions.
    """
    if doc.allow != "Chapter":
        return

    user = doc.user
    cache_key = f"accessible_chapters:{user}"
    frappe.cache.delete_value(cache_key)


def has_chapter_access(user: str, chapter: str, access_level: str = None) -> bool:
    """
    Check if a user has access to a specific chapter.

    Args:
        user: The user to check
        chapter: The chapter name to check access for
        access_level: Optional minimum access level required
                     (None, "Read Only", "Finance", "Full Access")

    Returns:
        True if user has access, False otherwise
    """
    if user == "Administrator":
        return True

    accessible = get_user_accessible_chapters(user)

    if chapter not in accessible:
        return False

    if access_level:
        user_level = get_user_access_level_for_chapter(user, chapter)
        level_order = {"Read Only": 1, "Finance": 2, "Full Access": 3}
        if user_level not in level_order:
            return False
        if level_order.get(access_level, 999) > level_order.get(user_level, 0):
            return False

    return True


def get_user_access_level_for_chapter(user: str, chapter: str) -> str | None:
    """
    Get the access level a user has for a specific chapter.

    Checks direct permission first, then walks up the hierarchy
    to find the nearest ancestor with a permission.

    Returns:
        Access level string or None if no access.
    """
    perm = frappe.db.get_value(
        "User Permission",
        {"user": user, "allow": "Chapter", "for_value": chapter},
        "access_level",
    )
    if perm:
        return perm or "Read Only"

    ancestors = get_ancestor_chapters(chapter)
    for ancestor in ancestors:
        perm = frappe.db.get_value(
            "User Permission",
            {"user": user, "allow": "Chapter", "for_value": ancestor},
            "access_level",
        )
        if perm:
            return perm or "Read Only"

    return None


def grant_chapter_access(user: str, chapter: str, access_level: str = "Read Only"):
    """
    Grant a user access to a chapter via User Permission.

    Args:
        user: User name (email)
        chapter: Chapter name
        access_level: "Full Access", "Finance", or "Read Only"
    """
    existing = frappe.db.exists(
        "User Permission",
        {"user": user, "allow": "Chapter", "for_value": chapter},
    )

    if existing:
        doc = frappe.get_doc("User Permission", existing)
        doc.access_level = access_level
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": user,
                "allow": "Chapter",
                "for_value": chapter,
                "access_level": access_level,
            }
        ).insert(ignore_permissions=True)

    clear_user_chapter_cache(type("Doc", (), {"user": user})(), None)


def revoke_chapter_access(user: str, chapter: str):
    """
    Revoke a user's access to a chapter.

    Args:
        user: User name (email)
        chapter: Chapter name
    """
    existing = frappe.db.exists(
        "User Permission",
        {"user": user, "allow": "Chapter", "for_value": chapter},
    )

    if existing:
        frappe.delete_doc("User Permission", existing, ignore_permissions=True)
        clear_user_chapter_cache(type("Doc", (), {"user": user})(), None)


@frappe.whitelist()
def get_members_for_chapter(chapter: str, include_descendants: bool = False):
    """
    Get all members for a chapter.

    Args:
        chapter: The chapter name
        include_descendants: If True, also include members from child chapters

    Returns:
        List of member records
    """
    chapters = [chapter]

    if include_descendants:
        chapters.extend(get_descendant_chapters(chapter))

    chapter_list = "', '".join([c.replace("'", "''") for c in chapters])

    return frappe.db.sql(
        f"""
        SELECT DISTINCT m.name, m.member_name, m.email_id, m.primary_chapter
        FROM `tabMember` m
        WHERE m.primary_chapter IN ('{chapter_list}')
        OR EXISTS (
            SELECT 1 FROM `tabChapter Member Role` cr
            WHERE cr.parent = m.name
            AND cr.chapter IN ('{chapter_list}')
            AND cr.is_active = 1
        )
        ORDER BY m.member_name
    """,
        as_dict=True,
    )


@frappe.whitelist()
def get_chapter_hierarchy(chapter: str = None):
    """
    Get the chapter hierarchy as a nested tree structure.

    Args:
        chapter: If provided, only return this chapter and its descendants

    Returns:
        Nested dict representing the chapter tree
    """
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

    def build_tree(items, parent=None):
        result = []
        for item in items:
            if item.parent_chapter == parent:
                children = build_tree(items, item.name)
                node = {
                    "name": item.name,
                    "chapter_type": item.chapter_type,
                    "region": item.region,
                    "children": children,
                }
                result.append(node)
        return result

    return build_tree(chapters)
