# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest
from unittest.mock import patch

import erpnext
import frappe

from non_profit.non_profit.doctype.donation.donation import create_gateway_donation
from non_profit.non_profit.doctype.donor.donor import get_donor_email, get_or_create_customer_for_donor


class TestDonation(unittest.TestCase):
    def setUp(self):
        company, receivable_account, cash_account = get_company_and_accounts()

        create_donor_type()
        settings = frappe.get_doc("Non Profit Settings")
        settings.company = company
        settings.donation_company = company
        settings.default_donor_type = "_Test Donor"
        settings.automate_donation_payment_entries = 1
        settings.donation_debit_account = receivable_account
        settings.donation_payment_account = cash_account
        settings.creation_user = "Administrator"
        settings.flags.ignore_permissions = True
        settings.save()

    def test_payment_entry_for_donations(self):
        donor = create_donor()
        create_mode_of_payment(
            frappe.get_cached_value("Non Profit Settings", None, "company")
        )
        payment = frappe._dict(
            {"amount": 100, "method": "Debit Card", "id": "pay_MeXAmsgeKOhq7O"}
        )
        donation = create_gateway_donation(donor, payment)

        self.assertTrue(donation.name)

        # Naive test to check if at all payment entry is generated
        # This method is actually triggered from Payment Gateway
        # In any case if details were missing, this would throw an error
        donation.db_set("paid", 1)
        donation.create_payment_entry(date=get_active_fiscal_year_date())
        donation.reload()

        self.assertEqual(donation.paid, 1)
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"reference_no": donation.name})
        )

    def test_payment_authorization_keeps_paid_state_when_payment_entry_fails(self):
        donor = create_donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": frappe.get_cached_value(
                    "Non Profit Settings", None, "company"
                ),
                "donor": donor.name,
                "donor_name": donor.donor_name,
                "email": get_donor_email(donor),
                "date": get_active_fiscal_year_date(),
                "amount": 25,
            }
        ).insert(ignore_permissions=True)
        donation.submit()

        with (
            patch.object(
                donation,
                "create_payment_entry",
                side_effect=RuntimeError("account mismatch"),
            ),
            patch("frappe.log_error") as log_error,
        ):
            donation.on_payment_authorized("Completed")

        donation.reload()
        self.assertEqual(donation.paid, 1)
        log_error.assert_called()

    def test_payment_entry_restores_account_permission_flag_on_failure(self):
        donor = create_donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": frappe.get_cached_value(
                    "Non Profit Settings", None, "company"
                ),
                "donor": donor.name,
                "donor_name": donor.donor_name,
                "email": get_donor_email(donor),
                "date": get_active_fiscal_year_date(),
                "amount": 25,
            }
        ).insert(ignore_permissions=True)
        donation.submit()

        original_flag = getattr(frappe.flags, "ignore_account_permission", False)
        frappe.flags.ignore_account_permission = False
        try:
            with patch(
                "non_profit.non_profit.custom_doctype.payment_entry.get_donation_payment_entry",
                side_effect=RuntimeError("boom"),
            ):
                with self.assertRaises(RuntimeError):
                    donation.create_payment_entry()
            self.assertFalse(frappe.flags.ignore_account_permission)
        finally:
            frappe.flags.ignore_account_permission = original_flag


def get_company_and_accounts():
    company_name = erpnext.get_default_company()
    company = frappe.get_doc("Company", company_name)
    return (
        company.name,
        company.default_receivable_account,
        company.default_cash_account,
    )


def get_active_fiscal_year_date():
    fiscal_year = frappe.get_all(
        "Fiscal Year",
        filters={"disabled": 0},
        fields=["year_start_date"],
        order_by="year_start_date desc",
        limit=1,
    )

    if fiscal_year:
        return fiscal_year[0].year_start_date

    return frappe.utils.getdate()


def create_donor_type():
    if not frappe.db.exists("Donor Type", "_Test Donor"):
        frappe.get_doc({"doctype": "Donor Type", "donor_type": "_Test Donor"}).insert()


def create_donor():
    donor = frappe.db.get_value("Donor", {"donor_name": "_Test Donor"}, "name", order_by="creation desc")
    if donor:
        donor_doc = frappe.get_doc("Donor", donor)
    else:
        donor_doc = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "_Test Donor",
                "donor_type": "_Test Donor",
            }
        ).insert()
    get_or_create_customer_for_donor(donor_doc, email="donor@test.com")
    donor_doc.reload()
    return donor_doc


def create_mode_of_payment(company):
    default_account = frappe.db.get_value("Company", company, "default_cash_account")
    account_row = {"company": company, "default_account": default_account}

    if not frappe.db.exists("Mode of Payment", "Debit Card"):
        frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": "Debit Card",
                "accounts": [account_row],
            }
        ).insert()
        return

    mop = frappe.get_doc("Mode of Payment", "Debit Card")
    if any(row.company == company for row in mop.accounts):
        return

    mop.append("accounts", account_row)
    mop.save(ignore_permissions=True)
