from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate


class TestDonationCampaign(FrappeTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        frappe.set_user("Administrator")

    def test_campaign_donation_chart_payload_has_monthly_buckets(self) -> None:
        from non_profit.non_profit.doctype.donation_campaign.donation_campaign import (
            get_campaign_donation_chart,
        )

        campaign = self._campaign()
        donation = self._donation(campaign=campaign.name, amount=42)

        payload = get_campaign_donation_chart(campaign.name)

        self.assertEqual(payload["campaign"], campaign.name)
        self.assertEqual(len(payload["year_options"]), 5)
        self.assertIn(payload["year"], payload["year_options"])
        self.assertEqual(len(payload["donations_by_month"]), 12)
        self.assertEqual(payload["donations_by_month"][0]["month"], 1)
        self.assertIn("total", payload["donations_by_month"][0])
        self.assertIn("segments", payload["donations_by_month"][0])
        self.assertTrue(
            any(
                segment["donation"] == donation.name
                for month in payload["donations_by_month"]
                for segment in month["segments"]
            )
        )

        previous_year_payload = get_campaign_donation_chart(
            campaign.name,
            year=payload["year_options"][1],
        )
        self.assertEqual(previous_year_payload["year"], payload["year_options"][1])
        self.assertEqual(len(previous_year_payload["donations_by_month"]), 12)

    def test_campaign_chart_script_owns_single_rendered_section(self) -> None:
        script = Path(
            frappe.get_app_path(
                "non_profit",
                "non_profit",
                "doctype",
                "donation_campaign",
                "donation_campaign.js",
            )
        ).read_text()

        self.assertIn("window.renderCampaignDonationChart?.(frm)", script)
        self.assertIn("non_profit_campaign_chart_request", script)
        self.assertNotIn(".good-npo-form-chart-section", script)
        self.assertIn("removeCampaignDonationChart(frm)", script)
        self.assertIn(
            "non_profit.non_profit.doctype.donation_campaign.donation_campaign.get_campaign_donation_chart",
            script,
        )
        self.assertIn("--non-profit-campaign-chart-height: 132px", script)
        self.assertIn("grid-template-columns: repeat(12, minmax(0, 1fr))", script)
        self.assertIn("grid-template-rows: var(--non-profit-campaign-chart-height) auto", script)
        self.assertIn("height: var(--non-profit-campaign-chart-height)", script)
        self.assertIn("overflow-x: clip", script)
        self.assertIn("width: 100%", script)
        self.assertIn(".non-profit-campaign-chart-section .section-body", script)
        self.assertIn("loading: false", script)
        self.assertIn("scrollTop: window.scrollY", script)
        self.assertIn("restoreScroll", script)

    def _campaign(self):
        suffix = frappe.generate_hash(length=8)
        return frappe.get_doc(
            {
                "doctype": "Donation Campaign",
                "campaign_name": f"Campaign Chart {suffix}",
                "campaign_code": f"CHART-{suffix}",
                "status": "Active",
                "currency": self._currency(),
            }
        ).insert(ignore_permissions=True)

    def _donation(self, campaign: str, amount: float):
        donor = self._donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": self._company(),
                "donor": donor.name,
                "donor_name": donor.donor_name,
                "campaign": campaign,
                "date": nowdate(),
                "amount": amount,
                "paid": 1,
            }
        ).insert(ignore_permissions=True)
        donation.submit()
        return donation

    def _donor(self):
        return frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": f"Campaign Donor {frappe.generate_hash(length=8)}",
                "donor_type": self._donor_type(),
            }
        ).insert(ignore_permissions=True)

    def _donor_type(self) -> str:
        name = f"Campaign Donor Type {frappe.generate_hash(length=8)}"
        frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
        return name

    def _company(self) -> str | None:
        return frappe.db.get_single_value("Non Profit Settings", "company") or frappe.db.get_value(
            "Company",
            {},
            "name",
            order_by="name asc",
        )

    def _currency(self) -> str | None:
        return frappe.db.get_default("currency") or frappe.db.get_value("Currency", {}, "name")
