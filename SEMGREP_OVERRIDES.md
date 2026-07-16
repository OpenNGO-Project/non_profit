# SEMGREP_OVERRIDES

## `guest-whitelisted-method` in `non_profit/non_profit/doctype/donation/donation.py`

- Rule: `guest-whitelisted-method`
- What it prevents: Accidental unauthenticated endpoints that expose or mutate private data.
- Why this override is safe: `mock_pay` is a development-only POST endpoint. It exits unless both `developer_mode` and the explicit `enable_non_profit_mock_payments` site-config flag are enabled, then only runs the same Donation payment hook used by verified gateway integrations.

## `frappe-manual-commit` in `non_profit/non_profit/doctype/recurring_donation/recurring_donation.py`

- Rule: `frappe-manual-commit`
- What it prevents: Manual commits inside request handlers or DocType hooks that can leave partial writes and bypass Frappe's transaction lifecycle.
- Why this override is safe: `process_recurring_donations` is a daily scheduler batch job. It commits each recurring-donation fan-out independently so one failing donor schedule can be rolled back and logged without undoing earlier generated Donations from the same batch run.
