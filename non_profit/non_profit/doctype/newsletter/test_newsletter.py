import frappe
from frappe.tests.utils import FrappeTestCase


class TestNewsletter(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()

    def test_newsletter_creation(self):
        email_group = frappe.get_doc(
            {
                "doctype": "Email Group",
                "title": "_Test Newsletter Group",
            }
        ).insert(ignore_if_duplicate=1)

        newsletter = frappe.get_doc(
            {
                "doctype": "Newsletter",
                "subject": "_Test Newsletter Subject",
                "email_group": email_group.name,
                "content": "<p>Test content</p>",
            }
        ).insert()

        self.assertEqual(newsletter.subject, "_Test Newsletter Subject")
        self.assertEqual(newsletter.status, "Draft")

    def test_recipient_count(self):
        email_group = frappe.get_doc(
            {
                "doctype": "Email Group",
                "title": "_Test Recipient Count Group",
            }
        ).insert(ignore_if_duplicate=1)

        member = frappe.get_doc(
            {
                "doctype": "Email Group Member",
                "email_group": email_group.name,
                "email": "test@example.com",
            }
        ).insert(ignore_if_duplicate=1)

        newsletter = frappe.get_doc(
            {
                "doctype": "Newsletter",
                "subject": "_Test Recipient Count",
                "email_group": email_group.name,
                "content": "<p>Test</p>",
            }
        ).insert()

        self.assertGreaterEqual(newsletter.total_recipients, 1)
