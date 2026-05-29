# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestChapter(FrappeTestCase):
    def test_create_chapter(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Chapter",
                "title": f"Test Chapter {frappe.generate_hash(length=6)}",
                "chapter_head": "Administrator",
                "region": "Test Region",
                "introduction": "Test introduction",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Chapter", doc.name))

    def test_route_is_auto_set_on_validate(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Chapter",
                "title": f"Route Test Chapter {frappe.generate_hash(length=6)}",
                "chapter_head": "Administrator",
                "region": "Test Region",
                "introduction": "Test introduction",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(doc.route)
        self.assertTrue(doc.route.startswith("chapters/"))

    def test_create_and_delete_chapter(self) -> None:
        doc = frappe.get_doc(
            {
                "doctype": "Chapter",
                "title": f"Delete Test Chapter {frappe.generate_hash(length=6)}",
                "chapter_head": "Administrator",
                "region": "Test Region",
                "introduction": "Test introduction",
            }
        ).insert(ignore_permissions=True)
        name = doc.name
        self.assertTrue(frappe.db.exists("Chapter", name))
        doc.delete()
        self.assertFalse(frappe.db.exists("Chapter", name))
