import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class DonationReceipt(Document):
	def validate(self):
		self._compute_total()
		if self.fiscal_year and not self.period_from:
			fy = frappe.get_doc("Fiscal Year", self.fiscal_year)
			self.period_from = fy.year_start_date
			self.period_to = fy.year_end_date

	def _compute_total(self):
		total = 0
		for row in self.donations or []:
			total += flt(row.amount)
		self.total_amount = total
		if not self.currency:
			self.currency = frappe.db.get_default("currency") or "EUR"

	def before_submit(self):
		self.status = "Issued"
		self.issued_on = nowdate()
		self.issued_by = frappe.session.user
		self._mark_donations()

	def _mark_donations(self):
		for row in self.donations or []:
			frappe.db.set_value("Donation", row.donation, "receipt", self.name)

	def on_cancel(self):
		self.status = "Cancelled"
		for row in self.donations or []:
			frappe.db.set_value("Donation", row.donation, "receipt", None)

	@frappe.whitelist()
	def send_to_donor(self):
		if not self.email:
			frappe.throw("No donor email")
		frappe.sendmail(
			recipients=[self.email],
			subject=f"Zuwendungsbestätigung {self.fiscal_year}",
			message=self._get_email_body(),
			attachments=[
				frappe.attach_print(
					self.doctype, self.name, print_format="Donation Receipt DE"
				)
			],
		)
		self.db_set("email_sent_on", nowdate())
		return True

	def _get_email_body(self):
		return f"""<p>Liebe/r {self.donor_name},</p>
<p>im Anhang erhalten Sie Ihre Zuwendungsbestätigung für das Jahr {self.fiscal_year}.</p>
<p>Herzlichen Dank für Ihre Unterstützung!</p>"""


@frappe.whitelist()
def generate_yearly_receipts(fiscal_year, country="Germany", language="de"):
	fy = frappe.get_doc("Fiscal Year", fiscal_year)
	start, end = fy.year_start_date, fy.year_end_date
	rows = frappe.db.sql(
		"""
		SELECT donor, donor_name, email, SUM(amount) AS total,
			   GROUP_CONCAT(name) AS donation_names
		FROM `tabDonation`
		WHERE docstatus = 1 AND paid = 1
		  AND date BETWEEN %s AND %s
		  AND (receipt IS NULL OR receipt = '')
		GROUP BY donor
		""",
		(start, end),
		as_dict=True,
	)
	created = []
	for row in rows:
		if not row.donor:
			continue
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": row.donor,
				"fiscal_year": fiscal_year,
				"period_from": start,
				"period_to": end,
				"country": country,
				"language": language,
				"donations": [
					{"donation": n}
					for n in (row.donation_names or "").split(",")
					if n
				],
			}
		)
		receipt.flags.ignore_permissions = True
		receipt.insert()
		created.append(receipt.name)
	frappe.db.commit()
	return {"created": len(created), "receipts": created}
