# AGENTS.md - non_profit

`non_profit` is the shared fundraising and membership substrate. Read the bench-root `AGENTS.md` first.

## Rules

- Keep generic Member, Membership, Donor, Donation, Receipt, Campaign, Sponsor, Volunteer, and Grant behavior here.
- Do not put client-specific UI, seeding, or branding in this app. Use `ilanga_app`, `good_npo`, or a client app for that.
- Miki depends on the membership substrate. If you change Member/Membership semantics, update `miki_app` in the same change.
- This app targets the Goodvantage bench and may depend on the ecosystem where
  it helps (ERPNext is a required app, so its `Task` doctype is always present;
  `good_connector` and friends are available). Do NOT bend the design to stay
  "standalone outside Goodvantage benches" — that constraint no longer applies.
  Defensive/optional imports (e.g. `good_connector.identity_matching` for legacy
  Member registration) are still fine as good practice, not as a hard mandate.
- Keep `HOW_TO.md` and `DOCUMENTATION.md` current when hooks, doctypes, public helpers, setup, scheduled jobs, or operational behavior change.
- All custom DocTypes must have Python controllers.
- All new `@frappe.whitelist()` functions need type hints.
- Public guest donations require GoodVantage CAPTCHA and fail closed when Good
  Connector or its CAPTCHA configuration is unavailable. Do not restore the
  former optional/exception-swallowing bypass.
- Desk form and list operations must use Frappe's Actions menu APIs
  (`frm.page.add_action_item`, `listview.page.add_action_item`, or
  `listview.page.add_actions_menu_item`) instead of visible inner-toolbar
  custom buttons, so Non Profit / GoodNPO views remain usable on mobile.
- Payment Entry integration is hook-based, not class-based. The Donation
  delta lives in the `before_validate` / `validate` and accounting-state
  `doc_events` handlers in
  `non_profit/non_profit/custom_doctype/payment_entry.py` (registered in
  `hooks.py`): `override_doctype_class` resolves to the last installed app
  (hrms wins on this bench), so the former `NonProfitPaymentEntry` controller
  override was silently inert. The class remains only as an import-compatible
  shell — never put required behaviour back on it. Donation carries
  maintained read-only `grand_total` / `advance_paid` custom-field mirrors
  (Sales Invoice semantics) so ERPNext's generic reference-details fallback
  computes the correct outstanding amount under any active Payment Entry
  controller; keep both fields in sync whenever the settlement state changes.
- Good Connector owns shared EBICS ingestion, settings, `gc_*` QRR/audit fields,
  aggregate ambiguity handling, and Bank Transaction linking. non_profit owns
  only Donation QRR registration, side-effect-free candidate matching, and the
  trusted unsaved Donation Payment Entry builder. Keep the existing qrbill
  Donation-slip renderer, but pass the shared QRR only for a real QR-IBAN.
  Candidate providers use deterministic ordered reads and return every
  same-QRR Donation before amount checks so amount filtering cannot select among
  ambiguous identities. Unsafe sole identities remain ineligible candidates.
  Good Connector locks the selected eligible target before building its Payment
  Entry. Automatic matching is company-currency only. QRR assignment serializes
  on the Company and rejects active same-company Donation/Sales Invoice collisions.
- Preserve valid stored QRRs as immutable compatibility data. Generate only a
  missing Donation reference through Good Connector's Donation namespace.
- Fundraising setup owns `Donation Receipt DE` and `Donation Slip CH` only while
  their HTML matches a known shipped hash. Keep the managed-hash allowlists
  append-only when changing shipped HTML so untouched rows upgrade; never add an
  operator-edited body to those allowlists. `Donation Thank You DE` remains
  create-only after first insertion.

## Documentation Contract

This repo keeps four synchronized artifacts: `REQUIREMENTS.md` (what the app
must do), `DOCUMENTATION.md` (how it works), `HOW_TO.md` (operator
procedures), and the code. Record new or changed requirements in
`REQUIREMENTS.md` and keep all four in sync with every change.

## Household Model

- **Household** + child **Household Member** (`link_doctype` Member/Donor,
  `link_name`, `from_date`, `to_date`, `is_primary`) model who belongs to a
  shared-address unit. A row without `to_date` is current; setting `to_date`
  makes history. The child table IS the history — for divorce/move-out set
  `to_date`, never delete the row.
- Party links are synced from `Household.on_update` via `frappe.db.set_value`
  (never by saving the party doc — that would recurse). Sync reconciles both
  current and persisted prior rows so removal, retargeting, history changes,
  and deletion cannot leave stale Member/Donor or Membership state.
- `Member.household` and `Donor.household` are read-only derived links. Change
  Household rows, or call
  `non_profit.non_profit.doctype.household.household.add_member_to_household`;
  never write either party field directly.
- Current rows require `from_date`, cannot have `to_date < from_date`, and must
  be unique per party. A Household may have at most one current primary, and a
  party may have at most one current Household. Validation locks affected
  party rows in deterministic order to serialize concurrent changes.
- Household access is restricted to `Non Profit Manager`, matching Donor
  access; service calls enforce write permission on both Household and Member
  unless an explicitly trusted caller passes `ignore_permissions=True`.
- `Membership.is_household_membership` is a read-only flag set in
  `Membership.validate` and refreshed on all Memberships when household links
  change. `Customer.household` and `Contact.title` are custom
  fields from `non_profit.setup.get_custom_fields`.
- Address/Contact attach to Household via standard Dynamic Links (same
  pattern as Member/Donor, including `load_address_and_contact` on `onload`).

## Smoke Commands

```bash
cd frappe-bench
bench --site development16.localhost run-tests --app non_profit
bench --site development16.localhost run-tests --module miki_app.tests.test_end_to_end
```

## List-View Search (applied 2026-07-10)

Applied per the bench-root convention (list views searchable by human title/name) —
these doctypes have a `title_field` (auto standard filter) but no or partial
`search_fields`, so Link typeahead only matches the serial ID:

- `Donor`: `search_fields: donor_name`.
- `Member`: `search_fields: member_name,email_id`.
- `Donor Interaction`: `search_fields: subject,donor_name`.
- `Major Gift`: `search_fields: donor_name`.
- `Grant Application`: `search_fields: applicant_name,email`.
- `Volunteer`: `search_fields: volunteer_name`.
- Already complete: Donation, Donation Campaign, Donation Receipt,
  Recurring Donation, Sponsor, Membership. Prompt-/field-named masters need
  nothing (Chapter, Volunteer Type, …).
