# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestNonProfitSettings(FrappeTestCase):
    def test_load_non_profit_settings(self) -> None:
        doc = frappe.get_doc("Non Profit Settings")
        self.assertEqual(doc.doctype, "Non Profit Settings")

    def test_save_non_profit_settings(self) -> None:
        doc = frappe.get_doc("Non Profit Settings")
        original = doc.send_email
        doc.send_email = 1
        doc.flags.ignore_permissions = True
        doc.save()
        doc.reload()
        self.assertEqual(doc.send_email, 1)
        doc.send_email = original
        doc.flags.ignore_permissions = True
        doc.save()
