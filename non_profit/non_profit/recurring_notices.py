"""Donor-facing notices for a recurring donation instruction.

Three moments need a message, and only three:

* the instruction is set up — the donor should have a record of what they just
  agreed to, and what it will cost them;
* a charge finally failed — after the provider stopped retrying, not before;
* the instruction stopped.

Deliberately **not** here: thanking the donor for each installment. A provider
installment is an ordinary paid Donation, so the existing Verdankung fires
through `Donation.on_payment_authorized` like it does for any other gift, and
the annual Bescheinigung aggregates them. Adding a second per-installment mail
would double every monthly donor's inbox.

Notices are best-effort for delivery failures. Database deadlocks and timeouts
propagate so the provider event boundary can roll back and retry atomically.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr, escape_html, fmt_money

from non_profit.non_profit.mailer import send_referenced_email

SIGNUP = "recurring_signup"
PAYMENT_FAILED = "recurring_payment_failed"
CANCELLED = "recurring_cancelled"


def notify(schedule, flow: str) -> bool:
	"""Send one donor notice, except that transient database failures propagate."""
	recipient = cstr(schedule.get("email")).strip()
	if not recipient:
		return False
	try:
		subject, message = _compose(schedule, flow)
		send_referenced_email(
			recipients=recipient,
			subject=subject,
			message=message,
			reference_doctype="Recurring Donation",
			reference_name=schedule.name,
		)
		return True
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):  # fmt: skip
		raise
	except Exception:
		# A failed notice must not undo the provider event that triggered it.
		frappe.log_error(
			title=f"Recurring donation notice failed: {flow}",
			message=frappe.get_traceback(),
		)
		return False


def _amount_label(schedule) -> str:
	return escape_html(fmt_money(schedule.get("amount"), currency=schedule.get("currency")))


def _compose(schedule, flow: str) -> tuple[str, str]:
	name = escape_html(cstr(schedule.get("donor_name")).strip() or _("Supporter"))
	amount = _amount_label(schedule)
	frequency = escape_html(_(cstr(schedule.get("frequency")) or ""))

	if flow == SIGNUP:
		return (
			_("Your recurring donation is set up"),
			_(
				"Dear {0}<br><br>Thank you for setting up a recurring donation of "
				"{1} ({2}).<br><br>You can change the amount or stop the donation at "
				"any time by replying to this email."
			).format(name, amount, frequency),
		)

	if flow == PAYMENT_FAILED:
		return (
			_("We could not collect your donation"),
			_(
				"Dear {0}<br><br>We were unable to collect your recurring donation of "
				"{1}. Your payment provider has stopped retrying, so no further "
				"attempts will be made.<br><br>Please reply to this email if you would "
				"like to set it up again."
			).format(name, amount),
		)

	if flow == CANCELLED:
		return (
			_("Your recurring donation has been stopped"),
			_(
				"Dear {0}<br><br>Your recurring donation of {1} has been stopped and "
				"you will not be charged again.<br><br>Thank you for your support."
			).format(name, amount),
		)

	raise ValueError(f"Unknown recurring notice flow: {flow}")
