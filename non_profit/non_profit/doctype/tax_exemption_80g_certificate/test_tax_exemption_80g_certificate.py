# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import copy
from types import MappingProxyType

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate
from frappe.tests.classes.integration_test_case import _restore_ctx_locals, _rollback_db

from erpnext.accounts.utils import get_fiscal_year
from non_profit.non_profit.doctype.donation.donation import create_razorpay_donation
from non_profit.non_profit.doctype.donation.test_donation import (
    create_donor,
    create_donor_type,
    create_mode_of_payment,
)
from non_profit.non_profit.doctype.member.member import create_member
from non_profit.non_profit.doctype.membership.test_membership import (
    make_membership,
    setup_membership,
)


class TestTaxExemption80GCertificate(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        if getattr(cls, "_integration_test_case_class_setup_done", None):
            return

        super(IntegrationTestCase, cls).setUpClass()

        cls.TEST_SITE = getattr(frappe.local, "site", None) or cls.TEST_SITE
        frappe.init(cls.TEST_SITE)
        cls.ADMIN_PASSWORD = frappe.get_conf(cls.TEST_SITE).admin_password

        cls._primary_connection = frappe.local.db
        cls._secondary_connection = None
        cls._newly_created_test_records = []

        frappe.db.commit()
        cls.globalTestRecords = MappingProxyType(frappe.local.test_objects)
        cls.addClassCleanup(_restore_ctx_locals, copy.deepcopy(frappe.local.flags))
        cls.addClassCleanup(_rollback_db)
        cls._integration_test_case_class_setup_done = True

    def setUp(self):
        frappe.db.sql("delete from `tabTax Exemption 80G Certificate`")
        frappe.db.sql("delete from `tabMembership`")
        create_donor_type()
        settings = frappe.get_doc("Non Profit Settings")
        settings.company = "_Test Company"
        settings.donation_company = "_Test Company"
        settings.default_donor_type = "_Test Donor"
        settings.creation_user = "Administrator"
        settings.save()

        company = frappe.get_doc("Company", "_Test Company")
        company.pan_details = "BBBTI3374C"
        company.company_80g_number = "NQ.CIT(E)I2018-19/DEL-IE28615-27062018/10087"
        company.with_effect_from = getdate()
        company.save()

    def test_duplicate_donation_certificate(self):
        suffix = frappe.generate_hash(length=8)
        donor = self.create_unique_donor(suffix)
        create_mode_of_payment()
        payment = frappe._dict(
            {
                "amount": 100,  # rzp sends data in paise
                "method": "Debit Card",
                "id": "pay_MeXAmsgeKOhq7O",
            }
        )
        donation = create_razorpay_donation(donor, payment)

        args = frappe._dict(
            {"recipient": "Donor", "donor": donor.name, "donation": donation.name}
        )
        certificate = create_80g_certificate(args)
        certificate.insert()

        # check company details
        self.assertEqual(certificate.company_pan_number, "BBBTI3374C")
        self.assertEqual(
            certificate.company_80g_number,
            "NQ.CIT(E)I2018-19/DEL-IE28615-27062018/10087",
        )

        # check donation details
        self.assertEqual(certificate.amount, donation.amount)

        duplicate_certificate = create_80g_certificate(args)
        # duplicate validation
        self.assertRaises(frappe.ValidationError, duplicate_certificate.insert)

    def test_membership_80g_certificate(self):
        plan = setup_membership()
        suffix = frappe.generate_hash(length=8)

        member_doc = create_member(
            frappe._dict(
                {
                    "fullname": f"_Test_Member_{suffix}",
                    "email": f"_test_member_{suffix}@example.com",
                    "plan_id": plan.name,
                }
            )
        )
        member = member_doc.name

        membership = make_membership(member, {"member_since_date": getdate()})
        membership.submit()
        invoice_name = frappe.db.get_value(
            "Sales Invoice", {"subscription": membership.subscription}, "name"
        )
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        args = frappe._dict(
            {
                "recipient": "Member",
                "member": member,
                "fiscal_year": get_fiscal_year(getdate(), as_dict=True).get("name"),
            }
        )
        certificate = create_80g_certificate(args)
        certificate.get_payments()
        certificate.insert()

        self.assertEqual(len(certificate.payments), 1)
        self.assertEqual(certificate.payments[0].amount, invoice.grand_total)
        self.assertEqual(certificate.payments[0].invoice_id, invoice.name)

    def create_unique_donor(self, suffix):
        from non_profit.non_profit.doctype.donor.donor import (
            create_donor_with_contact_and_customer,
        )

        return create_donor_with_contact_and_customer(
            email=f"donor-{suffix}@test.com",
            donor_type="_Test Donor",
            donor_name=f"_Test Donor {suffix}",
        )


def create_80g_certificate(args):
    certificate = frappe.get_doc(
        {
            "doctype": "Tax Exemption 80G Certificate",
            "recipient": args.recipient,
            "date": getdate(),
            "company": "_Test Company",
        }
    )

    certificate.update(args)

    return certificate
