from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from non_profit.www import donate


class TestDonatePage(FrappeTestCase):
    def test_guest_donation_requires_valid_captcha_when_configured(self) -> None:
        previous_user = frappe.session.user
        frappe.set_user("Guest")
        try:
            with patch(
                "non_profit.www.donate._captcha_site_key", return_value="site-key"
            ):
                with patch(
                    "non_profit.www.donate.verify_goodvantage_captcha_response",
                    return_value=False,
                ) as verify:
                    with self.assertRaises(frappe.ValidationError):
                        donate._verify_captcha(
                            {donate.GOODVANTAGE_CAPTCHA_RESPONSE_FIELD: "bad-token"}
                        )
                verify.assert_called_once_with("bad-token")
        finally:
            frappe.set_user(previous_user)

    def test_guest_donation_allows_unconfigured_optional_captcha(self) -> None:
        previous_user = frappe.session.user
        frappe.set_user("Guest")
        try:
            with patch("non_profit.www.donate._captcha_site_key", return_value=""):
                with patch(
                    "non_profit.www.donate.verify_goodvantage_captcha_response"
                ) as verify:
                    donate._verify_captcha({})
                verify.assert_not_called()
        finally:
            frappe.set_user(previous_user)
