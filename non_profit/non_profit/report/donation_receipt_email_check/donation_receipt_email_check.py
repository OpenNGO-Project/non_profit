"""
Donation Receipt Email Check — data quality for the annual receipt run.

Receipts have gone to the wrong person before, and the cause is master data
rather than transport: a donor with no email, a typo'd address, two donors
sharing one inbox, or a Donor form showing one address while the receipt
resolves to another through the contact/customer chain.

This report lists exactly those donors *before* the batch goes out, so the run
can be corrected instead of apologised for. It reports on the address the
receipt would actually be sent to — `get_donor_email`, the same resolver
`send_receipt_email` uses — not on whatever is typed on the Donor form.

Severity is `Blocker` when the receipt cannot be sent or would certainly go to
the wrong inbox, and `Warning` when it merits a look.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, validate_email_address

from non_profit.non_profit.doctype.donor.donor import get_donor_email

# Shared mailboxes are the classic "receipt went to the wrong person" case: the
# address resolves fine, but it is not the donor's personal inbox.
ROLE_ADDRESS_PREFIXES = (
	"info",
	"kontakt",
	"contact",
	"office",
	"buero",
	"verwaltung",
	"post",
	"mail",
	"noreply",
	"no-reply",
	"admin",
	"vorstand",
	"geschaeftsstelle",
)

BLOCKER = "Blocker"
WARNING = "Warning"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{
			"fieldname": "severity",
			"label": _("Severity"),
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"fieldname": "issue",
			"label": _("Issue"),
			"fieldtype": "Data",
			"width": 230,
		},
		{
			"fieldname": "donor",
			"label": _("Donor"),
			"fieldtype": "Link",
			"options": "Donor",
			"width": 150,
		},
		{
			"fieldname": "donor_name",
			"label": _("Donor Name"),
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"fieldname": "receipt_email",
			"label": _("Receipt Email"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "shared_with",
			"label": _("Also Used By"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "donation_total",
			"label": _("Donations"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "donation_count",
			"label": _("Gifts"),
			"fieldtype": "Int",
			"width": 80,
		},
	]


def get_data(filters) -> list[dict]:
	donors = _donors_in_scope(filters)
	if not donors:
		return []

	resolved = {donor["name"]: cstr(get_donor_email(donor["name"])).strip() for donor in donors}
	sharers = _shared_addresses(resolved)

	rows = []
	for donor in donors:
		email = resolved[donor["name"]]
		for severity, issue, shared_with in _issues(donor, email, sharers):
			rows.append(
				{
					"severity": severity,
					"issue": issue,
					"donor": donor["name"],
					"donor_name": donor.get("donor_name"),
					"receipt_email": email or "",
					"shared_with": shared_with,
					"donation_total": donor.get("donation_total") or 0,
					"donation_count": donor.get("donation_count") or 0,
				}
			)

	# Blockers first, then by size of the gift at risk.
	rows.sort(key=lambda row: (row["severity"] != BLOCKER, -(row["donation_total"] or 0)))
	return rows


def _issues(donor: dict, email: str, sharers: dict[str, list[str]]):
	"""Yield (severity, issue, shared_with) for one donor."""
	if not email:
		yield BLOCKER, _("No email address; receipt cannot be sent"), ""
		return

	if not _is_valid(email):
		yield BLOCKER, _("Email address is not valid"), ""
		return

	others = [name for name in sharers.get(email.lower(), []) if name != donor["name"]]
	if others:
		yield (
			BLOCKER,
			_("Email shared with {0} other donor(s)").format(len(others)),
			", ".join(others[:5]),
		)

	if _is_role_address(email):
		yield WARNING, _("Shared or role mailbox, not a personal address"), ""

	form_email = _donor_form_email(donor["name"])
	if form_email and form_email.lower() != email.lower():
		yield (
			WARNING,
			_("Donor record shows a different address than the receipt would use"),
			form_email,
		)


def _donors_in_scope(filters) -> list[dict]:
	"""Donors with qualifying donations, optionally narrowed to one tax year."""
	donation = frappe.qb.DocType("Donation")
	query = (
		frappe.qb.from_(donation)
		.select(
			donation.donor,
			frappe.query_builder.functions.Sum(donation.amount).as_("donation_total"),
			frappe.query_builder.functions.Count(donation.name).as_("donation_count"),
		)
		.where(donation.docstatus == 1)
		.groupby(donation.donor)
	)

	if filters.get("company"):
		query = query.where(donation.company == filters.company)

	if filters.get("tax_year"):
		year = cint(filters.tax_year)
		query = query.where(donation.date >= f"{year}-01-01").where(donation.date <= f"{year}-12-31")

	totals = {row["donor"]: row for row in query.run(as_dict=True) if row["donor"]}
	if not totals:
		return []

	donors = frappe.get_all(
		"Donor",
		filters={"name": ["in", list(totals)]},
		fields=["name", "donor_name"],
		limit_page_length=0,
	)

	for donor in donors:
		donor["donation_total"] = totals[donor["name"]]["donation_total"]
		donor["donation_count"] = totals[donor["name"]]["donation_count"]

	return donors


def _shared_addresses(resolved: dict[str, str]) -> dict[str, list[str]]:
	shared: dict[str, list[str]] = {}
	for donor, email in resolved.items():
		if not email:
			continue
		shared.setdefault(email.lower(), []).append(donor)
	return {email: donors for email, donors in shared.items() if len(donors) > 1}


def _donor_form_email(donor: str) -> str:
	"""The address a user sees on the Donor form, via its canonical contact."""
	contact = frappe.db.get_value("Donor", donor, "contact")
	if not contact:
		return ""
	return cstr(frappe.db.get_value("Contact", contact, "email_id")).strip()


def _is_valid(email: str) -> bool:
	try:
		return bool(validate_email_address(email, throw=False))
	except Exception:
		return False


def _is_role_address(email: str) -> bool:
	local = email.split("@", 1)[0].lower()
	return any(local == prefix or local.startswith(f"{prefix}.") for prefix in ROLE_ADDRESS_PREFIXES)
