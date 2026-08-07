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
