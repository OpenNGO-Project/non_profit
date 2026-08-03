"""Provider-hook seams for optional private integrations.

This repository is PUBLIC (see AGENTS.md). It must never import private
apps by module path — doing so leaks private module layouts into a public
codebase and breaks external adopters who install non_profit standalone.

Private apps register providers under the hook names below instead. Every
seam degrades gracefully when no provider is installed: the dependent
feature is skipped or reports itself unavailable, and nothing raises
ImportError.
"""

from __future__ import annotations

from collections.abc import Callable

import frappe

CONTACT_RESOLUTION = "non_profit_contact_resolution_providers"
ADDRESS_RESOLUTION = "non_profit_address_resolution_providers"
CAPTCHA = "non_profit_captcha_providers"
QR_REFERENCE_REGISTRATION = "non_profit_qr_reference_providers"
QR_REFERENCE_BACKFILL = "non_profit_qr_reference_backfill_providers"
BANK_INTEGRATION_SETUP = "non_profit_bank_integration_setup_hooks"


def first_provider(hook_name: str) -> Callable | None:
	"""Return the first registered provider callable, or None.

	Registration order is Frappe app-install order; the first provider wins
	because these seams model a single integration backend, not a chain.
	"""
	for dotted_path in frappe.get_hooks(hook_name) or []:
		return frappe.get_attr(dotted_path)
	return None
