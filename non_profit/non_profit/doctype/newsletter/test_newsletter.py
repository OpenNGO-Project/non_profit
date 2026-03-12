import frappe
from frappe.tests import IntegrationTestCase


class TestNewsletter(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_newsletter_creation(self):
        suffix = frappe.generate_hash(length=8)
        email_group = frappe.get_doc(
            {
                "doctype": "Email Group",
                "title": f"_Test Newsletter Group {suffix}",
            }
        ).insert()

        newsletter = frappe.get_doc(
            {
                "doctype": "Newsletter",
                "subject": f"_Test Newsletter Subject {suffix}",
                "content": "<p>Test content</p>",
            }
        )
        newsletter.append("email_groups", {"email_group": email_group.name})
        newsletter.insert()

        self.assertEqual(newsletter.subject, f"_Test Newsletter Subject {suffix}")
        self.assertEqual(newsletter.status, "Draft")

    def test_recipient_count(self):
        suffix = frappe.generate_hash(length=8)
        email_group = frappe.get_doc(
            {
                "doctype": "Email Group",
                "title": f"_Test Recipient Count Group {suffix}",
            }
        ).insert()

        frappe.get_doc(
            {
                "doctype": "Email Group Member",
                "email_group": email_group.name,
                "email": f"test-{suffix}@example.com",
            }
        ).insert()

        newsletter = frappe.get_doc(
            {
                "doctype": "Newsletter",
                "subject": f"_Test Recipient Count {suffix}",
                "content": "<p>Test</p>",
            }
        )
        newsletter.append("email_groups", {"email_group": email_group.name})
        newsletter.insert()

        self.assertGreaterEqual(newsletter.total_recipients, 1)
