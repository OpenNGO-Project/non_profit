# SEMGREP_OVERRIDES

## `guest-whitelisted-method` in `non_profit/non_profit/doctype/donation/donation.py`

- Rule: `guest-whitelisted-method`
- What it prevents: Accidental unauthenticated endpoints that expose or mutate private data.
- Why this override is safe: `mock_pay` is a development-only POST endpoint. It exits unless both `developer_mode` and the explicit `enable_non_profit_mock_payments` site-config flag are enabled, then only runs the same Donation payment hook used by verified gateway integrations.

## `frappe-manual-commit` in `non_profit/non_profit/doctype/recurring_donation/recurring_donation.py`

- Rule: `frappe-manual-commit`
- What it prevents: Manual commits inside request handlers or DocType hooks that can leave partial writes and bypass Frappe's transaction lifecycle.
- Why this override is safe: `process_recurring_donations` is a daily scheduler batch job. It commits each recurring-donation fan-out independently so one failing donor schedule can be rolled back and logged without undoing earlier generated Donations from the same batch run.

## `frappe-manual-commit` in `non_profit/scripts/donation_slip_smoke.py`

- Rule: `frappe-manual-commit`
- What it prevents: Manual transaction commits in ordinary request or document lifecycle code.
- Why this override is safe: This is an operator-invoked bench smoke script, not a request handler or DocType hook. It deliberately commits the isolated fixture it creates so a separate PDF render command can read it.

## `frappe-ssti` in `non_profit/non_profit/doctype/donation/donation.py`

- Rule: `frappe-ssti`
- What it prevents: Rendering attacker-controlled Jinja that could expose server-side data or execute unsafe template operations.
- Why this override is safe: Donation thank-you content comes from the configured `Email Template` document, whose write access is restricted to trusted Desk administrators. The donor controls neither the template subject nor body; only the Donation values supplied as rendering context.

## `frappe-manual-commit` in Donation concurrency tests

- Rule: `frappe-manual-commit`
- What it prevents: Manual commits in application request and document lifecycle code.
- Why this override is safe: The two commits occur only in a MariaDB integration test that opens independent database connections. The first publishes fixtures so both workers can exercise the allocation race; the second persists cross-connection cleanup. Production code does not use these commits.

## `frappe-manual-commit` in Donation Receipt concurrency tests

- Rule: `frappe-manual-commit`
- What it prevents: Manual commits in application request and document lifecycle code.
- Why this override is safe: The six commits occur only in MariaDB integration tests (`test_donation_receipt.py`) that open independent database connections to reproduce receipt reservation and cursor-page races. Two publish fixtures so both worker connections can see them, two persist cross-connection cleanup, and two run inside the worker helpers so each worker's own connection makes its race outcome visible to the other. Production code does not use these commits.

## `frappe-ssti` in `non_profit/non_profit/doctype/membership/membership.py`

- Rule: `frappe-ssti`
- What it prevents: Rendering attacker-controlled Jinja that could expose server-side data or execute unsafe template operations.
- Why this override is safe: The membership acknowledgement subject and body come from the `Email Template` document configured in Non Profit Settings, whose write access is restricted to trusted Desk administrators. The member controls neither template; only the Membership and Member values supplied as rendering context.
