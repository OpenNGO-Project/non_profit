import frappe
from frappe import _
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
			frappe.throw(_("End Date cannot be before Start Date"))
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
		# run_doc_method only enforces read permission; inserting and
		# submitting a Donation is a write-level action.
		self.check_permission("write")
		_lock_recurring_donation(self.name)
		self.load_from_db()
		donation = self._get_or_create_current_donation()
		self.advance_next_date()
		self.save()
		return donation.name

	def _get_or_create_current_donation(self):
		existing = frappe.db.get_value(
			"Donation",
			{
				"recurring_donation": self.name,
				"date": self.next_date,
				"docstatus": ["<", 2],
			},
			"name",
			order_by="creation asc",
		)
		return frappe.get_doc("Donation", existing) if existing else self.create_donation(mark_paid=False)


def process_recurring_donations():
	"""Daily scheduler: fan out due recurring donations into Donation records."""
	today = getdate(nowdate())
	due = frappe.get_all(
		"Recurring Donation",
		filters={"status": "Active", "next_date": ["<=", today]},
		fields=["name", "next_date"],
		order_by="name asc",
	)
	for candidate in due:
		name = candidate.name
		try:
			_lock_recurring_donation(name)
			rec = frappe.get_doc("Recurring Donation", name)
			if (
				rec.status != "Active"
				or not rec.next_date
				or getdate(rec.next_date) != getdate(candidate.next_date)
				or getdate(rec.next_date) > today
			):
				frappe.db.rollback()
				continue
			rec._get_or_create_current_donation()
			rec.advance_next_date()
			rec.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
		except Exception:
			frappe.log_error(title=f"Recurring Donation fan-out failed: {name}")
			frappe.db.rollback()


def _lock_recurring_donation(name: str) -> None:
	recurring = frappe.qb.DocType("Recurring Donation")
	(frappe.qb.from_(recurring).select(recurring.name).where(recurring.name == name).for_update()).run()
