from erpnext.accounts.doctype.bank_transaction.bank_transaction import BankTransaction

from non_profit.non_profit.custom_doctype.payment_entry import (
	sync_donation_reconciliation_state_for_payment_entry_name,
)


class NonProfitBankTransaction(BankTransaction):
	def clear_linked_payment_entry(self, payment_entry, clearance_date=None):
		super().clear_linked_payment_entry(payment_entry, clearance_date=clearance_date)
		if payment_entry.payment_document == "Payment Entry" and payment_entry.payment_entry:
			sync_donation_reconciliation_state_for_payment_entry_name(payment_entry.payment_entry)
