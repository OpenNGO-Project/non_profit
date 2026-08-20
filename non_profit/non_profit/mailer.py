"""Doc-referenced outbound email dispatch for non_profit.

Dispatches to ``non_profit_referenced_email_providers`` hooks first, so a
downstream delivery app can create a traceable Communication on the reference
document's timeline without this public repository importing it. When no
provider is registered, delivery falls back to plain ``frappe.sendmail`` with
the same arguments.
"""

from __future__ import annotations

from typing import Any

import frappe

REFERENCED_EMAIL_PROVIDER_HOOK = "non_profit_referenced_email_providers"


def send_referenced_email(
	*,
	recipients: list[str] | str,
	subject: str,
	message: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	attachments: list[dict[str, Any]] | None = None,
	**sendmail_options: Any,
) -> Any:
	"""Send a doc-referenced email through the registered provider hook.

	The last registered provider wins (the most downstream app). Provider
	errors propagate to the caller — falling back to ``frappe.sendmail``
	after a provider failure could double-send. Recipient, subject, and
	template behavior stay with the caller; only the dispatch mechanism
	and timeline linkage are decided here.
	"""
	if isinstance(recipients, str):
		recipients = [recipients]
	kwargs: dict[str, Any] = dict(
		recipients=recipients,
		subject=subject,
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		attachments=attachments,
		**sendmail_options,
	)
	providers = frappe.get_hooks(REFERENCED_EMAIL_PROVIDER_HOOK) or []
	if providers:
		return frappe.get_attr(providers[-1])(**kwargs)
	return frappe.sendmail(**kwargs)


def send_queued_email_now(email_queue: Any) -> None:
	"""Deliver one just-queued transactional mail without waiting for the scheduler.

	``frappe.sendmail`` only queues. The queue is flushed by the ``all``
	scheduler bucket, which runs every few minutes and additionally skips rows
	younger than a ten-second undo window — fine for a batch, wrong for a
	button. Someone who clicked *send this receipt* should not be told it went
	out and then watch nothing arrive for four minutes.

	Takes the queue returned by :func:`send_referenced_email`, so there is no
	race with the row's creation. Delivery runs as Administrator because the
	staff member who pressed the button has no rights on ``Email Queue`` —
	the decision to send was already made and authorised by then.

	Failure is deliberately swallowed: the row stays queued and the scheduler
	will retry it, which is exactly the behaviour without this call.
	"""
	name = str(getattr(email_queue, "name", "") or email_queue or "")
	if not name:
		return
	frappe.enqueue(
		"non_profit.non_profit.mailer._send_email_queue_as_administrator",
		queue="short",
		enqueue_after_commit=True,
		deduplicate=True,
		job_id=f"non_profit_send_email_queue:{name}",
		email_queue_name=name,
	)


def _send_email_queue_as_administrator(email_queue_name: str) -> None:
	from frappe.email.doctype.email_queue.email_queue import send_now

	user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if frappe.db.get_value("Email Queue", email_queue_name, "status") == "Not Sent":
			send_now(email_queue_name)
	except Exception:
		frappe.log_error(
			title="Non Profit: queued email could not be sent immediately",
			message=frappe.get_traceback(),
		)
	finally:
		frappe.set_user(user)
