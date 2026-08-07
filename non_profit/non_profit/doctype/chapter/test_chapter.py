# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from non_profit.non_profit.doctype.chapter.chapter import join


class TestChapter(IntegrationTestCase):
	def test_create_chapter(self) -> None:
		chapter_head = _make_member()
		title = f"Test Chapter {frappe.generate_hash(length=6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Chapter",
				"name": title,
				"title": title,
				"chapter_head": chapter_head,
				"region": "Test Region",
				"introduction": "Test introduction",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Chapter", doc.name))

	def test_route_is_auto_set_on_validate(self) -> None:
		chapter_head = _make_member()
		title = f"Route Test Chapter {frappe.generate_hash(length=6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Chapter",
				"name": title,
				"title": title,
				"chapter_head": chapter_head,
				"region": "Test Region",
				"introduction": "Test introduction",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.route)
		self.assertTrue(doc.route.startswith("chapters/"))

	def test_create_and_delete_chapter(self) -> None:
		chapter_head = _make_member()
		title = f"Delete Test Chapter {frappe.generate_hash(length=6)}"
		doc = frappe.get_doc(
			{
				"doctype": "Chapter",
				"name": title,
				"title": title,
				"chapter_head": chapter_head,
				"region": "Test Region",
				"introduction": "Test introduction",
			}
		).insert(ignore_permissions=True)
		name = doc.name
		self.assertTrue(frappe.db.exists("Chapter", name))
		doc.delete()
		self.assertFalse(frappe.db.exists("Chapter", name))

	def test_logged_in_user_can_join_published_chapter_as_self(self) -> None:
		chapter_head = _make_member()
		user = _make_user()
		title = f"Join Test Chapter {frappe.generate_hash(length=6)}"
		chapter = frappe.get_doc(
			{
				"doctype": "Chapter",
				"name": title,
				"title": title,
				"chapter_head": chapter_head,
				"region": "Test Region",
				"introduction": "Test introduction",
				"published": 1,
			}
		).insert(ignore_permissions=True)

		previous_user = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				join(chapter.name)

			frappe.set_user(user)
			join(chapter.name, introduction="Hello", website_url="https://example.com")
		finally:
			frappe.set_user(previous_user)

		chapter.reload()
		members = [row for row in chapter.members if row.user == user and row.enabled]
		self.assertEqual(len(members), 1)
		self.assertEqual(members[0].introduction, "Hello")
		self.assertEqual(members[0].website_url, "https://example.com")

	def test_join_rejects_non_http_website_url(self) -> None:
		chapter_head = _make_member()
		user = _make_user()
		title = f"URL Test Chapter {frappe.generate_hash(length=6)}"
		chapter = frappe.get_doc(
			{
				"doctype": "Chapter",
				"name": title,
				"title": title,
				"chapter_head": chapter_head,
				"region": "Test Region",
				"introduction": "Test introduction",
				"published": 1,
			}
		).insert(ignore_permissions=True)

		previous_user = frappe.session.user
		try:
			frappe.set_user(user)
			# The URL is rendered as a link on the public chapter page, so
			# javascript:/data: payloads must be rejected server-side.
			for bad_url in ("javascript:alert(1)", "data:text/html,x", "ftp://example.com"):
				with self.assertRaises(frappe.ValidationError):
					join(chapter.name, website_url=bad_url)
		finally:
			frappe.set_user(previous_user)


def _make_member() -> str:
	name = f"Chapter Head {frappe.generate_hash(length=6)}"
	doc = frappe.get_doc(
		{
			"doctype": "Member",
			"member_name": name,
		}
	).insert(ignore_permissions=True)
	return doc.name


def _make_user() -> str:
	email = f"chapter-member-{frappe.generate_hash(length=8)}@example.com"
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Chapter",
			"last_name": "Member",
			"send_welcome_email": 0,
			"user_type": "Website User",
		}
	).insert(ignore_permissions=True)
	return email
