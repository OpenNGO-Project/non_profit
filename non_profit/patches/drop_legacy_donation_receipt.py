"""Remove the retired legacy `Donation Receipt` Bescheinigung model (16.10.0).

`Donation Tax Receipt` is the single Spendenbescheinigung since non_profit
16.10.0. The older submittable `Donation Receipt` (+ child `Donation Receipt
Item`) was a second Bescheinigung model and is gone from the codebase; this
patch removes whatever a site still carries: the Print Formats bound to the
retired DocType, the DocType rows themselves, and their tables.

Idempotent: every step is guarded by an existence check, so re-running or
running on a site that never had the DocTypes is a no-op.
"""

import frappe

CHILD_DOCTYPE = "Donation Receipt Item"
PARENT_DOCTYPE = "Donation Receipt"
RETIRED_DOCTYPES = (CHILD_DOCTYPE, PARENT_DOCTYPE)


def execute() -> None:
	for print_format in frappe.get_all("Print Format", filters={"doc_type": PARENT_DOCTYPE}, pluck="name"):
		frappe.delete_doc("Print Format", print_format, force=True, ignore_missing=True)

	# Child first: deleting the parent DocType would otherwise leave the child
	# behind as an orphan that `bench migrate` re-reports on every run.
	for doctype in RETIRED_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)

	for doctype in RETIRED_DOCTYPES:
		_drop_retired_table(doctype)

	frappe.clear_cache()


def _drop_retired_table(doctype: str) -> None:
	if doctype not in RETIRED_DOCTYPES:
		raise ValueError(f"Refusing to drop non-retired DocType table: {doctype}")
	if frappe.db.table_exists(doctype, cached=False):
		# Raw DDL: Frappe has no ORM verb for dropping a table whose DocType
		# is already gone. The identifier comes from the fixed allowlist above.
		frappe.db.sql_ddl(f"drop table `tab{doctype}`")
