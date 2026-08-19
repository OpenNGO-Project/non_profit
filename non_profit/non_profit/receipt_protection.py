"""
Password protection for emailed Spendenbescheinigungen.

Receipts have been sent to the wrong inbox before, and the mitigation the
sector reaches for is a password on the PDF. Be precise about what that buys:
this is *access protection*, not encryption in transit. The mail still travels
as ordinary SMTP, anyone who can read the mailbox still sees the sender and the
subject, and frappe's `get_pdf` uses pypdf's default (RC4-128) cipher. What it
does stop is a receipt that landed in the wrong inbox from being *read* — which
is the actual reported incident.

The real fix is master data quality; see the `Donation Receipt Email Check`
report, which lists the donors whose address would misfire before the annual
batch goes out. This module is the belt to that report's braces.

Encryption itself is frappe's: `attach_print(password=...)` already routes
through `get_pdf`, which encrypts the writer. All this module decides is
*whether* to pass a password and *what* it should be.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr

PASSWORD_SOURCES = ("Postal Code", "Donor ID")
DEFAULT_PASSWORD_SOURCE = "Postal Code"


def receipt_protection_enabled() -> bool:
	return bool(frappe.db.get_single_value("Non Profit Settings", "protect_receipt_pdf"))


def receipt_password(donor: str) -> str | None:
	"""
	The password a donor needs to open their receipt, or None when protection
	is switched off.

	Deliberately derived from data the donor already knows and the organisation
	already stores, so nothing has to be communicated out of band.
	"""
	if not receipt_protection_enabled():
		return None

	source = (
		frappe.db.get_single_value("Non Profit Settings", "receipt_pdf_password_source")
		or DEFAULT_PASSWORD_SOURCE
	)

	if source == "Donor ID":
		return cstr(donor).strip()

	if source == "Postal Code":
		return _donor_postal_code(donor)

	frappe.throw(_("Unknown PDF password source {0}.").format(source))


def _donor_postal_code(donor: str) -> str:
	address = _primary_address(donor)
	pincode = cstr(frappe.db.get_value("Address", address, "pincode")).strip() if address else ""

	if not pincode:
		# Sending an unprotected receipt when protection was switched on would
		# silently defeat the setting, so this refuses instead.
		frappe.throw(
			_(
				"Donor {0} has no postal code, so the receipt PDF cannot be password-protected. "
				"Add an address or change the PDF Password Source."
			).format(frappe.bold(donor))
		)

	return pincode


def _primary_address(donor: str) -> str | None:
	"""
	The donor's address.

	Addresses hang off whichever identity record the data came in on, so all
	three links are tried in the order a receipt would prefer them: the Donor
	itself, then its canonical Contact, then its Customer.
	"""
	values = frappe.db.get_value("Donor", donor, ["contact", "customer"], as_dict=True) or {}

	link_targets = [("Donor", donor)]
	if values.get("contact"):
		link_targets.append(("Contact", values["contact"]))
	if values.get("customer"):
		link_targets.append(("Customer", values["customer"]))

	for link_doctype, link_name in link_targets:
		addresses = frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Address",
				"link_doctype": link_doctype,
				"link_name": link_name,
			},
			pluck="parent",
			order_by="creation",
		)
		for address in addresses:
			if frappe.db.get_value("Address", address, "is_primary_address"):
				return address
		if addresses:
			return addresses[0]

	return None
