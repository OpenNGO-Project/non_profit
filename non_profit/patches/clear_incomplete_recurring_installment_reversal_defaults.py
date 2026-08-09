import frappe

BATCH_SIZE = 100
CONTAMINATED_SOURCE = "Accounting"
CONTAMINATED_KIND = "Payment Entry Cancellation"
REVERSAL_FIELDS = (
	"reversal_source",
	"reversal_kind",
	"reversal_reference",
	"reversal_date",
	"reversal_amount",
	"reversal_recorded_on",
)


def execute() -> None:
	if not frappe.db.table_exists("Recurring Donation Installment") or not all(
		frappe.db.has_column("Recurring Donation Installment", fieldname) for fieldname in REVERSAL_FIELDS
	):
		return

	installment = frappe.qb.DocType("Recurring Donation Installment")
	last_name = ""
	while True:
		query = (
			frappe.qb.from_(installment)
			.select(installment.name)
			.where(installment.reversal_source == CONTAMINATED_SOURCE)
			.where(installment.reversal_kind == CONTAMINATED_KIND)
			.where(installment.reversal_reference.isnull() | (installment.reversal_reference == ""))
			.where(installment.reversal_date.isnull())
			.where(installment.reversal_amount.isnull() | (installment.reversal_amount == 0))
			.where(installment.reversal_recorded_on.isnull())
		)
		if last_name:
			query = query.where(installment.name > last_name)
		names = query.orderby(installment.name).limit(BATCH_SIZE).run(pluck=True)
		if not names:
			break
		for name in names:
			frappe.db.set_value(
				"Recurring Donation Installment",
				name,
				{"reversal_source": None, "reversal_kind": None},
				update_modified=False,
			)
		last_name = names[-1]
