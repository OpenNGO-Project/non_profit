import frappe
from frappe.tests import UnitTestCase

from non_profit.non_profit.utils import contact_display_name, customer_display_name


class TestPublicDisplayNameHelpers(UnitTestCase):
	def test_customer_display_name_normalizes_parts_and_fallback(self) -> None:
		self.assertEqual(
			customer_display_name(" Example Foundation ", " Zurich "), "Example Foundation - Zurich"
		)
		self.assertEqual(customer_display_name("Example Foundation", ""), "Example Foundation")
		self.assertEqual(customer_display_name("", " Zurich "), "Zurich")
		self.assertEqual(customer_display_name("", None, fallback="CUSTOMER-1"), "CUSTOMER-1")

	def test_contact_display_name_uses_documented_precedence(self) -> None:
		contact = frappe._dict(
			name="CONTACT-1",
			full_name=" Preferred Full Name ",
			first_name="First",
			last_name="Last",
		)
		self.assertEqual(contact_display_name(contact), "Preferred Full Name")

		contact.full_name = ""
		contact.first_name = " First "
		contact.last_name = " Last "
		self.assertEqual(contact_display_name(contact), "First Last")

		contact.first_name = ""
		contact.last_name = ""
		self.assertEqual(contact_display_name(contact), "CONTACT-1")
		self.assertEqual(contact_display_name(contact, fallback="Imported Contact"), "Imported Contact")
