from typing import Any

import frappe
import erpnext

from frappe import _, scrub
from frappe.query_builder import Order
from frappe.utils.data import comma_or, flt, getdate
from frappe.query_builder.functions import Sum

from erpnext.accounts.doctype.invoice_discounting.invoice_discounting import (
    get_party_account_based_on_invoice_discounting,
)
from erpnext.accounts.doctype.journal_entry.journal_entry import (
    get_default_bank_cash_account,
)
from erpnext.accounts.doctype.payment_entry.payment_entry import (
    PaymentEntry,
    get_outstanding_on_journal_entry,
)

from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency
from erpnext.setup.utils import get_exchange_rate


class NonProfitPaymentEntry(PaymentEntry):
    def on_submit(self):
        super().on_submit()
        sync_donation_accounting_state_for_payment_entry(self)

    def on_cancel(self):
        super().on_cancel()
        sync_donation_accounting_state_for_payment_entry(self)

    def on_change(self):
        super_on_change = getattr(super(), "on_change", None)
        if callable(super_on_change):
            super_on_change()
        if self.docstatus == 1:
            sync_donation_reconciliation_state_for_payment_entry(self)

    def validate_reference_documents(self):
        if self.party_type == "Student":
            valid_reference_doctypes = ("Fees", "Journal Entry")
        elif self.party_type == "Customer":
            valid_reference_doctypes = (
                "Sales Order",
                "Sales Invoice",
                "Journal Entry",
                "Dunning",
            )
        elif self.party_type == "Supplier":
            valid_reference_doctypes = (
                "Purchase Order",
                "Purchase Invoice",
                "Journal Entry",
            )
        elif self.party_type == "Employee":
            valid_reference_doctypes = (
                "Expense Claim",
                "Journal Entry",
                "Employee Advance",
            )
        elif self.party_type == "Shareholder":
            valid_reference_doctypes = "Journal Entry"
        elif self.party_type == "Donor":
            valid_reference_doctypes = "Donation"

        for d in self.get("references"):
            if not d.allocated_amount:
                continue
            if d.reference_doctype not in valid_reference_doctypes:
                frappe.throw(
                    _("Reference Doctype must be one of {0}").format(
                        comma_or(valid_reference_doctypes)
                    )
                )
            elif d.reference_name:
                if not frappe.db.exists(d.reference_doctype, d.reference_name):
                    frappe.throw(
                        _("{0} {1} does not exist").format(
                            d.reference_doctype, d.reference_name
                        )
                    )
                else:
                    ref_doc = frappe.get_doc(d.reference_doctype, d.reference_name)
                    if d.reference_doctype != "Journal Entry":
                        if self.party != ref_doc.get(scrub(self.party_type)):
                            frappe.throw(
                                _("{0} {1} is not associated with {2} {3}").format(
                                    d.reference_doctype,
                                    d.reference_name,
                                    self.party_type,
                                    self.party,
                                )
                            )
                    else:
                        self.validate_journal_entry()
                    if d.reference_doctype in (
                        "Sales Invoice",
                        "Purchase Invoice",
                        "Expense Claim",
                        "Fees",
                    ):
                        if self.party_type == "Customer":
                            ref_party_account = (
                                get_party_account_based_on_invoice_discounting(
                                    d.reference_name
                                )
                                or ref_doc.debit_to
                            )
                        elif self.party_type == "Student":
                            ref_party_account = ref_doc.receivable_account
                        elif self.party_type == "Supplier":
                            ref_party_account = ref_doc.credit_to
                        elif self.party_type == "Employee":
                            ref_party_account = ref_doc.payable_account
                        if ref_party_account != self.party_account:
                            frappe.throw(
                                _(
                                    "{0} {1} is associated with {2}, but Party Account is {3}"
                                ).format(
                                    d.reference_doctype,
                                    d.reference_name,
                                    ref_party_account,
                                    self.party_account,
                                )
                            )
                    if ref_doc.docstatus != 1:
                        frappe.throw(
                            _("{0} {1} must be submitted").format(
                                d.reference_doctype, d.reference_name
                            )
                        )

    def set_missing_ref_details(
        self,
        force: bool = False,
        update_ref_details_only_for: list | None = None,
        reference_exchange_details: dict | None = None,
    ) -> None:
        for d in self.get("references"):
            if d.allocated_amount:
                if (
                    update_ref_details_only_for
                    and (d.reference_doctype, d.reference_name)
                    not in update_ref_details_only_for
                ):
                    continue

                ref_details = get_payment_reference_details(
                    d.reference_doctype,
                    d.reference_name,
                    self.party_account_currency,
                    self.party_type,
                    self.party,
                )

                # Only update exchange rate when the reference is Journal Entry
                if (
                    reference_exchange_details
                    and d.reference_doctype
                    == reference_exchange_details.reference_doctype
                    and d.reference_name == reference_exchange_details.reference_name
                ):
                    ref_details.update(
                        {"exchange_rate": reference_exchange_details.exchange_rate}
                    )

                for field, value in ref_details.items():
                    if d.exchange_gain_loss:
                        # for cases where gain/loss is booked into invoice
                        # exchange_gain_loss is calculated from invoice & populated
                        # and row.exchange_rate is already set to payment entry's exchange rate
                        # refer -> `update_reference_in_payment_entry()` in utils.py
                        continue

                    if field == "exchange_rate" or not d.get(field) or force:
                        d.db_set(field, value)


@frappe.whitelist()
def get_donation_payment_entry(
    dt: str,
    dn: str,
    party_amount: float | None = None,
    bank_account: str | None = None,
    bank_amount: float | None = None,
) -> Any:
    reference_doc = None
    doc = frappe.get_doc(dt, dn)

    party_account = get_party_account("Donor", doc.get("donor"), doc.company)
    party_account_currency = doc.get("party_account_currency") or get_account_currency(
        party_account
    )
    grand_total, outstanding_amount = set_grand_total_and_outstanding_amount(
        party_amount, doc
    )

    # bank or cash
    bank = get_bank_cash_account(doc, bank_account)

    paid_amount, received_amount = set_paid_amount_and_received_amount(
        party_account_currency, bank, outstanding_amount, bank_amount, doc
    )

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.company = doc.company
    pe.cost_center = doc.get("cost_center")
    pe.posting_date = getdate()
    pe.mode_of_payment = doc.get("mode_of_payment")
    pe.party_type = "Donor"
    pe.party = doc.get("donor")
    pe.contact_person = doc.get("contact_person")
    pe.contact_email = doc.get("contact_email")

    pe.paid_from = party_account
    pe.paid_to = bank.account
    pe.paid_from_account_currency = party_account_currency
    pe.paid_to_account_currency = bank.account_currency
    pe.paid_amount = paid_amount
    pe.received_amount = received_amount
    pe.letter_head = doc.get("letter_head")

    pe.append(
        "references",
        {
            "reference_doctype": dt,
            "reference_name": dn,
            "bill_no": doc.get("bill_no"),
            "due_date": doc.get("due_date"),
            "total_amount": grand_total,
            "outstanding_amount": outstanding_amount,
            "allocated_amount": outstanding_amount,
        },
    )

    pe.setup_party_account_field()
    pe.set_missing_values()

    if party_account and bank:
        pe.set_exchange_rate(ref_doc=reference_doc)
        pe.set_amounts()

    return pe


def set_grand_total_and_outstanding_amount(party_amount, doc):
    grand_total = outstanding_amount = 0
    if party_amount:
        grand_total = outstanding_amount = party_amount
    else:
        grand_total = doc.amount
        outstanding_amount = doc.amount

    return grand_total, outstanding_amount


def get_bank_cash_account(doc, bank_account):
    bank = get_default_bank_cash_account(
        doc.company,
        "Bank",
        mode_of_payment=doc.get("mode_of_payment"),
        account=bank_account,
    )

    if not bank:
        bank = get_default_bank_cash_account(
            doc.company,
            "Cash",
            mode_of_payment=doc.get("mode_of_payment"),
            account=bank_account,
        )

    return bank


def set_paid_amount_and_received_amount(
    party_account_currency, bank, outstanding_amount, bank_amount, doc
):
    paid_amount = received_amount = 0
    if party_account_currency == bank.account_currency:
        paid_amount = received_amount = abs(outstanding_amount)
    else:
        paid_amount = abs(outstanding_amount)
        if bank_amount:
            received_amount = bank_amount
        else:
            received_amount = paid_amount * doc.get("conversion_rate", 1)

    return paid_amount, received_amount


def sync_donation_accounting_state_for_payment_entry(payment_entry) -> None:
    sync_donation_paid_state_for_payment_entry(payment_entry)
    sync_donation_reconciliation_state_for_payment_entry(payment_entry)


def sync_donation_paid_state_for_payment_entry(payment_entry) -> None:
    donation_names = _donation_names_for_payment_entry(payment_entry)
    for donation_name in donation_names:
        sync_donation_paid_state(donation_name)


def sync_donation_paid_state(donation_name: str) -> None:
    if not frappe.db.exists("Donation", donation_name):
        return

    donation_amount, current_paid = frappe.db.get_value(
        "Donation",
        donation_name,
        ["amount", "paid"],
    )
    paid = (
        1
        if _submitted_donation_payment_total(donation_name) >= flt(donation_amount)
        else 0
    )
    if int(current_paid or 0) != paid:
        frappe.db.set_value(
            "Donation", donation_name, "paid", paid, update_modified=False
        )


def _submitted_donation_payment_total(donation_name: str) -> float:
    payment_entry = frappe.qb.DocType("Payment Entry")
    payment_reference = frappe.qb.DocType("Payment Entry Reference")
    total = (
        frappe.qb.from_(payment_reference)
        .inner_join(payment_entry)
        .on(payment_entry.name == payment_reference.parent)
        .select(Sum(payment_reference.allocated_amount))
        .where(payment_entry.docstatus == 1)
        .where(payment_reference.reference_doctype == "Donation")
        .where(payment_reference.reference_name == donation_name)
    ).run()[0][0]
    return flt(total)


def sync_donation_reconciliation_state_for_payment_entry(payment_entry) -> None:
    donation_names = _donation_names_for_payment_entry(payment_entry)
    for donation_name in donation_names:
        sync_donation_reconciliation_state(donation_name)


def sync_donation_reconciliation_state_for_payment_entry_name(
    payment_entry_name: str,
) -> None:
    for donation_name in _donation_names_for_payment_entry_name(payment_entry_name):
        sync_donation_reconciliation_state(donation_name)


def sync_donation_reconciliation_state(donation_name: str) -> None:
    if not frappe.db.exists("Donation", donation_name):
        return

    donation_meta = frappe.get_meta("Donation")
    if not donation_meta.has_field("reconciled"):
        return

    donation = frappe.db.get_value(
        "Donation",
        donation_name,
        ["amount", "reconciled", "reconciled_on", "reconciled_payment_entry"],
        as_dict=True,
    )
    if not donation:
        return

    reconciled_payment = _submitted_reconciled_donation_payment_details(donation_name)
    reconciled = 1 if reconciled_payment.total >= flt(donation.amount) else 0
    reconciled_on = reconciled_payment.clearance_date if reconciled else None
    reconciled_payment_entry = reconciled_payment.payment_entry if reconciled else None

    updates = {}
    if int(donation.reconciled or 0) != reconciled:
        updates["reconciled"] = reconciled
    if (
        donation_meta.has_field("reconciled_on")
        and donation.reconciled_on != reconciled_on
    ):
        updates["reconciled_on"] = reconciled_on
    if (
        donation_meta.has_field("reconciled_payment_entry")
        and donation.reconciled_payment_entry != reconciled_payment_entry
    ):
        updates["reconciled_payment_entry"] = reconciled_payment_entry

    if updates:
        frappe.db.set_value("Donation", donation_name, updates, update_modified=False)


def _donation_names_for_payment_entry(payment_entry) -> set[str]:
    return {
        row.reference_name
        for row in payment_entry.get("references")
        if row.reference_doctype == "Donation" and row.reference_name
    }


def _donation_names_for_payment_entry_name(payment_entry_name: str) -> set[str]:
    payment_reference = frappe.qb.DocType("Payment Entry Reference")
    rows = (
        frappe.qb.from_(payment_reference)
        .select(payment_reference.reference_name)
        .where(payment_reference.parent == payment_entry_name)
        .where(payment_reference.reference_doctype == "Donation")
        .where(payment_reference.reference_name.isnotnull())
    ).run()
    return {row[0] for row in rows if row[0]}


def _submitted_reconciled_donation_payment_details(donation_name: str) -> frappe._dict:
    payment_entry = frappe.qb.DocType("Payment Entry")
    payment_reference = frappe.qb.DocType("Payment Entry Reference")
    rows = (
        frappe.qb.from_(payment_reference)
        .inner_join(payment_entry)
        .on(payment_entry.name == payment_reference.parent)
        .select(
            payment_entry.name,
            payment_entry.clearance_date,
            payment_reference.allocated_amount,
        )
        .where(payment_entry.docstatus == 1)
        .where(payment_entry.clearance_date.isnotnull())
        .where(payment_entry.clearance_date != "0000-00-00")
        .where(payment_reference.reference_doctype == "Donation")
        .where(payment_reference.reference_name == donation_name)
        .orderby(payment_entry.clearance_date, order=Order.desc)
        .orderby(payment_entry.name, order=Order.desc)
    ).run(as_dict=True)

    if not rows:
        return frappe._dict(total=0, clearance_date=None, payment_entry=None)

    return frappe._dict(
        total=sum(flt(row.allocated_amount) for row in rows),
        clearance_date=rows[0].clearance_date,
        payment_entry=rows[0].name,
    )


@frappe.whitelist()
def get_payment_reference_details(
    reference_doctype: str,
    reference_name: str,
    party_account_currency: str,
    party_type: str | None = None,
    party: str | None = None,
) -> dict[str, Any]:
    total_amount = outstanding_amount = exchange_rate = bill_no = None
    ref_doc = frappe.get_doc(reference_doctype, reference_name)
    company_currency = ref_doc.get("company_currency") or erpnext.get_company_currency(
        ref_doc.company
    )

    if reference_doctype == "Fees":
        total_amount = ref_doc.get("grand_total")
        exchange_rate = 1
        outstanding_amount = ref_doc.get("outstanding_amount")
    elif reference_doctype == "Donation":
        total_amount = ref_doc.get("amount")
        outstanding_amount = total_amount
        exchange_rate = 1
    elif reference_doctype == "Dunning":
        total_amount = ref_doc.get("dunning_amount")
        exchange_rate = 1
        outstanding_amount = ref_doc.get("dunning_amount")
    elif reference_doctype == "Journal Entry" and ref_doc.docstatus == 1:
        total_amount = ref_doc.get("total_amount")
        if ref_doc.multi_currency:
            exchange_rate = get_exchange_rate(
                party_account_currency, company_currency, ref_doc.posting_date
            )
        else:
            exchange_rate = 1
            outstanding_amount = get_outstanding_on_journal_entry(
                reference_name, party_type, party
            )
    elif reference_doctype != "Journal Entry":
        if ref_doc.doctype == "Expense Claim":
            total_amount = flt(ref_doc.total_sanctioned_amount) + flt(
                ref_doc.total_taxes_and_charges
            )
        elif ref_doc.doctype == "Employee Advance":
            total_amount = ref_doc.advance_amount
            exchange_rate = ref_doc.get("exchange_rate")
            if party_account_currency != ref_doc.currency:
                total_amount = flt(total_amount) * flt(exchange_rate)
        elif ref_doc.doctype == "Gratuity":
            total_amount = ref_doc.amount
        if not total_amount:
            if party_account_currency == company_currency:
                total_amount = ref_doc.base_grand_total
                exchange_rate = 1
            else:
                total_amount = ref_doc.grand_total
        if not exchange_rate:
            # Get the exchange rate from the original ref doc
            # or get it based on the posting date of the ref doc.
            exchange_rate = ref_doc.get("conversion_rate") or get_exchange_rate(
                party_account_currency, company_currency, ref_doc.posting_date
            )
        if reference_doctype in ("Sales Invoice", "Purchase Invoice"):
            outstanding_amount = ref_doc.get("outstanding_amount")
            bill_no = ref_doc.get("bill_no")
        elif reference_doctype == "Expense Claim":
            outstanding_amount = (
                flt(ref_doc.get("total_sanctioned_amount"))
                + flt(ref_doc.get("total_taxes_and_charges"))
                - flt(ref_doc.get("total_amount_reimbursed"))
                - flt(ref_doc.get("total_advance_amount"))
            )
        elif reference_doctype == "Employee Advance":
            outstanding_amount = flt(ref_doc.advance_amount) - flt(ref_doc.paid_amount)
            if party_account_currency != ref_doc.currency:
                outstanding_amount = flt(outstanding_amount) * flt(exchange_rate)
                if party_account_currency == company_currency:
                    exchange_rate = 1
        elif reference_doctype == "Gratuity":
            outstanding_amount = ref_doc.amount - flt(ref_doc.paid_amount)
        else:
            outstanding_amount = flt(total_amount) - flt(ref_doc.advance_paid)
    else:
        # Get the exchange rate based on the posting date of the ref doc.
        exchange_rate = get_exchange_rate(
            party_account_currency, company_currency, ref_doc.posting_date
        )

    return frappe._dict(
        {
            "due_date": ref_doc.get("due_date"),
            "total_amount": flt(total_amount),
            "outstanding_amount": flt(outstanding_amount),
            "exchange_rate": flt(exchange_rate),
            "bill_no": bill_no,
        }
    )
