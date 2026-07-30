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
- Public Donor, Customer, Contact, Member, and Membership creation shares the
  hashed `non-profit-identity` Redis lock namespace. Normalized individual
  emails use identity type `Individual`; leases renew while the transaction is
  open, are revalidated before commit, and release on commit or rollback. Keep
  renewal bounded and fail the transaction if ownership is lost.
- Donation Receipt submission and yearly generation lock complete current
  Donation/receipt ownership state. Yearly generation is permission-aware and
  chained in bounded batches grouped by Company, Company currency, Donor,
  country, and period. Later cursor pages must extend the locked exact-match
  draft instead of splitting one logical group; never restore the former
  synchronous unbounded flow.
- Swiss receipt email delivery requires a submitted issued receipt, deterministic
  issuer/recipient Addresses, and the operator-selected approved Swiss Print
  Format. `Donation Receipt DE` is never valid for that send path.
- `before_tests` may bootstrap an entirely empty test site and refresh app-owned
  fixtures, but must never delete shared rows, rename ERPNext records, or mutate
  global Customer, Fiscal Year, Address, Item Price, or Email Account state.
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

- **Household** + child **Household Person** (`contact`, `relationship`,
  `from_date`, `to_date`, `is_primary`) model a shared-address unit by canonical
  Contact. A row without `to_date` is current; for divorce/move-out set
  `to_date` so the child table retains history.
- Household sync projects one Contact's current Household onto every linked
  Member/Donor role via `frappe.db.set_value` (never by saving the role). It
  reconciles current and prior rows and refreshes Membership flags.
- `Member.household` and `Donor.household` are read-only role projections.
  Change Household rows or call
  `non_profit.non_profit.doctype.household.household.add_person_to_household`;
  never write those role fields directly.
- Current rows require `from_date`, reject invalid date order, are unique per
  Contact, and allow one current primary. A Contact has at most one current
  Household. Validation locks affected Contacts deterministically.
- Blank legacy Contact identity kinds become `Person`; explicit
  `Generic Endpoint` Contacts are rejected from person roles/Households, and a
  Contact already used there cannot be reclassified as a Generic Endpoint.
- Canonical role Contact assignment is conflict-checked against both the hidden
  role field and existing Contact Dynamic Links, and one Contact can back at
  most one role of each type. Never add, clear, or retarget it on an existing
  role with a raw save or `frappe.db.set_value`; use the owning identity helper.
- Household access is restricted to `Non Profit Manager`; service calls enforce
  write permission on Household and Contact unless a trusted caller passes
  `ignore_permissions=True`.
- `Membership.is_household_membership` is a read-only flag set in
  `Membership.validate` and refreshed on all Memberships when household links
  change. `Customer.household`, `Contact.title`, and hidden standard-master NPO
  identity fields come from `non_profit.setup.get_custom_fields` on install and
  migrate.
- Address/Contact attach to Household via standard Dynamic Links (same
  pattern as Member/Donor, including `load_address_and_contact` on `onload`).
- Postal consumers must resolve Contact/Member/Donor/Household/Customer through
  `non_profit.non_profit.correspondence`; it is bounded, read-only, keeps
  person sources as people for explicit later Household consolidation, accepts
  canonical subjects with bounded related Contact/Member/Donor/Customer rows,
  and never treats `Generic Endpoint` as a person or guesses among multiple
  Addresses. Related rows may supply language/address candidates but must never
  replace the caller's canonical Contact, Customer, or Household.
- Joint giving uses one Household-subject Donor resolved through
  `get_or_create_donor_for_household()`. The helper locks only the Household
  parent row, reuses one canonical or legacy blank-subject-type Household Donor,
  and fails on multiple candidates; do not create a Household Customer or
  attribute joint giving to the primary Household person.
- The 16.3.0 `Household Member` -> `Household Person` replacement is protected
  by ordered pre/post model-sync patches. Never remove, move after model sync,
  or weaken their fail-closed identity/date checks; an ambiguous production row
  must stop migration rather than be guessed or deleted.

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
