from non_profit.patches.backfill_recurring_donation_installments import execute as rebuild_installments


def execute() -> None:
	rebuild_installments()
