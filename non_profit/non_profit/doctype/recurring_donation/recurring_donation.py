import frappe
from frappe.model.document import Document
from frappe.utils import add_months, add_years, getdate, nowdate

from non_profit.non_profit.doctype.donor.donor import get_donor_email


class RecurringDonation(Document):
    def validate(self):
        if self.donor:
            self.email = get_donor_email(self.donor) or self.email
        if not self.start_date:
            self.start_date = nowdate()
        if not self.next_date:
            self.next_date = self.start_date
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw("End Date cannot be before Start Date")
        if not self.currency:
            self.currency = frappe.db.get_default("currency") or "EUR"

    def advance_next_date(self):
        if self.frequency == "Monthly":
            self.next_date = add_months(getdate(self.next_date), 1)
        elif self.frequency == "Quarterly":
            self.next_date = add_months(getdate(self.next_date), 3)
        elif self.frequency == "Yearly":
            self.next_date = add_years(getdate(self.next_date), 1)
        if self.end_date and getdate(self.next_date) > getdate(self.end_date):
            self.status = "Cancelled"

    def create_donation(self, mark_paid=False):
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor,
                "donor_name": self.donor_name,
                "email": self.email,
                "company": self.company,
                "date": self.next_date,
                "amount": self.amount,
                "mode_of_payment": self.mode_of_payment,
                "campaign": self.campaign,
                "recurring_donation": self.name,
            }
        )
        donation.flags.ignore_permissions = True
        donation.insert()
        donation.submit()
        if mark_paid:
            donation.db_set("paid", 1)
            donation.load_from_db()
            donation.run_method("create_payment_entry")
        return donation

    @frappe.whitelist()
    def create_next_donation(self) -> str:
        donation = self.create_donation(mark_paid=False)
        self.advance_next_date()
        self.save()
        return donation.name


def process_recurring_donations():
    """Daily scheduler: fan out due recurring donations into Donation records."""
    today = getdate(nowdate())
    due = frappe.get_all(
        "Recurring Donation",
        filters={"status": "Active", "next_date": ["<=", today]},
        pluck="name",
    )
    for name in due:
        try:
            rec = frappe.get_doc("Recurring Donation", name)
            rec.create_donation(mark_paid=False)
            rec.advance_next_date()
            rec.save(ignore_permissions=True)
            frappe.db.commit()  # nosemgrep: frappe-manual-commit
        except Exception:
            frappe.log_error(title=f"Recurring Donation fan-out failed: {name}")
            frappe.db.rollback()
