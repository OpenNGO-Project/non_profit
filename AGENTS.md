# AGENTS.md - non_profit

`non_profit` is the shared fundraising and membership substrate. Read the bench-root `AGENTS.md` first.

## Rules

- Keep generic Member, Membership, Donor, Donation, Bescheinigung, Campaign, Sponsor, Volunteer, and Grant behavior here.
- Do not put client-specific UI, seeding, or branding in this app. Use `ilanga_app`, `good_npo`, or a client app for that.
- Miki depends on the membership substrate. If you change Member/Membership semantics, update `miki_app` in the same change.
- This repository is PUBLIC (github.com/OpenNGO-Project/non_profit); the rest
  of the Goodvantage ecosystem (`good_connector`, `good_npo`, `miki_app`,
  `good_event`, ...) is private. Do not add new imports of or references to
  private apps here. Where private behavior is needed, expose a neutral
  provider hook (e.g. `non_profit_qr_bill_svg_providers`) and let a private
  app — usually `good_npo` — register the implementation. The existing
  guarded soft-imports (e.g. in `bank_integration.py`) are legacy seams to
  migrate onto hooks over time, not a pattern to extend. ERPNext remains a
  required app, so its doctypes may be used freely.
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
  trusted unsaved Donation Payment Entry builder. The public app owns only the
  neutral `non_profit_qr_bill_svg_providers` print seam and has no standalone
  QR renderer. A downstream provider owns the complete regulated payment part
  and passes the shared QRR only for a real QR-IBAN; this public repo itself
  must not import a private app in the print path. Retryable database errors
  from providers propagate unchanged and without logging.
  `Non Profit Settings.creditor_iban` is the optional public provider override;
  the shared deployment provider checks it before the Donation Company's
  default Bank Account. Keep account validation and fallback resolution in the
  provider.
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
- `Contact.preferred_language` is owned by module `Non Profit` on a standalone
  install. When Good Connector is installed, non_profit setup must preserve its
  module `Good Connector` claim; Good Connector uninstall hands ownership back
  before cleanup when non_profit remains installed.
- **There is exactly one Bescheinigung: `Donation Tax Receipt`.** The legacy
  submittable `Donation Receipt` (+ `Donation Receipt Item`) was removed in
  16.10.0 (operator decision 2026-07-31, convergence plan Phase 2b). Do not
  reintroduce a second receipt model, and never reuse the retired `NPO-DRCPT-`
  naming-series prefix. A **Verdankung** (`Donation.thank_you_sent`, and the
  planned `Donation Acknowledgement`) is a different document — do not conflate
  the two.
- `Donation Tax Receipt` (Spendenbescheinigung) is the annual per-donor/year/company
  receipt.
  Its business rules live in `non_profit/non_profit/tax_receipts.py`; letter
  production and postal dispatch belong to `good_direct_mail`. Never import
  `good_direct_mail` at module level — the single call into it goes through
  `frappe.get_attr` and is guarded by a `frappe.db.exists("DocType", ...)` check —
  and never move receipt business rules (which donations qualify, tax-year
  aggregation, dedup) into the direct-mail app. The audience crosses the boundary
  only as `good_direct_mail_audience_providers` rows; `producer_context` values
  must stay scalar and the `*_html` table must be built and escaped here.
  Receipt insert/delete and generated-field changes go through the
  module-private receipt-write capability sentinel in the controller; never
  replace it with a bare boolean flag. Generation includes only submitted paid
  Donations, validates Company access and CHF, serializes on Company before
  current-row locking reads, deletes stale Drafts, and reports stale Issued rows.
  The postal provider returns Drafts only. Default mark-issued selection includes
  only canonical postal subjects; pass explicit posted receipt names when known.
  Cancellation goes through the audited POST-only service/action.
- Individual receipt email delivery (`tax_receipts.send_receipt_email`) gates on
  document `read` **plus** the DocType `email` right, accepts only Draft/Issued
  receipts, resolves the donor address through `get_donor_email`, attaches the
  seeded `Spendenbescheinigung` Print Format, and stamps `email_sent_on`.
  Emailing must never change the receipt status — `Issued` stays the explicit
  `mark_receipts_issued` action.
- `before_tests` may bootstrap an entirely empty test site and refresh app-owned
  fixtures, but must never delete shared rows, rename ERPNext records, or mutate
  global Customer, Fiscal Year, Address, Item Price, or Email Account state.
- Fundraising setup owns the `Spendenbescheinigung` and `Donation Slip CH` Print
  Formats only while their HTML matches a known shipped hash. Keep the
  managed-hash allowlists append-only when changing shipped HTML so untouched
  rows upgrade; never add an operator-edited body to those allowlists.
  `Donation Thank You DE` remains create-only after first insertion. The
  Spendenbescheinigung format is Swiss/CHF: it carries the German layout and
  wording of the retired `Donation Receipt DE` but never its German income-tax
  paragraphs.

## Documentation Contract

This repo keeps four synchronized artifacts: `REQUIREMENTS.md` (what the app
must do), `DOCUMENTATION.md` (how it works), `HOW_TO.md` (operator
procedures), and the code. Record new or changed requirements in
`REQUIREMENTS.md` and keep all four in sync with every change.

## Recipient Selection Contract

- `NPO Recipient Selection` is the generic saved Contact/Member/Donor audience
  definition. Keep channel-neutral selection and canonical identity behavior in
  `non_profit.non_profit.recipient_selection`; consuming campaign apps must not
  duplicate these joins.
- `get_recipient_selection_rows(selection, channel)` returns deterministic raw
  rows keyed by canonical Contact, Customer, or explicit Household and enforces
  selection/source read permissions plus enabled/channel gates. Preserve its
  compatibility with `good_direct_mail.services.preparation.merge_source_rows`.
- `get_recipient_selection_configuration(selection)` is the versioned hashing
  input for consumers. Add every result-affecting saved criterion before using a
  new field in selection queries; do not include transient counts or timestamps.
- `channel_launch` is the neutral source-form coordinator. Channel apps register
  through `non_profit_audience_channel_creators`; never import or name private
  channel apps in Python. Optional source apps register through
  `non_profit_audience_source_providers`. Keep the launcher transactional,
  fieldtype-allowlisted, permission-filtered through channel-owned availability
  callbacks, and source transforms ordered before ordinary channels. Dialog
  fields are mandatory only while their channel is selected.
- Optional source apps must reuse `donor_source_rows` /
  `newsletter_members_from_donors` rather than copying Donor canonicalization or
  correspondence rules.
- Contacts include only blank/Person identity kinds. Members canonicalize
  Contact first through active Membership rows; only Organization or blank legacy
  subjects may fall back to Customer. Donors canonicalize explicit/compatible
  legacy Household first, then Contact, with the same Organization/blank legacy
  Customer fallback. Generic Endpoint, permission-invisible, unsupported, and
  missing canonical identities never qualify. Keep evaluation bounded to 10,000
  raw source rows.
- The optional Good Newsletter provider remains import-free and resolves
  correspondence profiles in batches of at most 500. It uses Customer email
  before deterministic linked person Contacts, current Household people primary
  first, excludes `Contact.unsubscribed`, fails closed for inaccessible related
  Contacts, batches complete permission-aware email reads, and deduplicates email
  case-insensitively. A candidate it cannot reach still yields a row with an
  empty `email` so good_newsletter can report it as `skipped_no_email`; do not
  "clean up" those rows out of the payload.
- User-facing selection consumers call correspondence resolution with
  `respect_permissions=True`; permission-invisible related identity and Address
  rows must not influence names, language, email, or postal readiness.

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
bench --site development16.localhost run-tests --module non_profit.non_profit.test_tax_receipts
bench --site development16.localhost run-tests --module non_profit.non_profit.test_fundraising_setup
bench --site development16.localhost run-tests --module miki_app.tests.test_end_to_end
```

## List-View Search (applied 2026-07-10)

Applied per the bench-root convention (list views searchable by human title/name) —
these doctypes have a `title_field` (auto standard filter) but no or partial
`search_fields`, so Link typeahead only matches the serial ID:

- `Donation Tax Receipt`: `title_field: donor_name`, `search_fields: donor_name,tax_year`.
- `Donor`: `search_fields: donor_name`.
- `Member`: `search_fields: member_name,email_id`.
- `Major Gift`: `search_fields: donor_name`.
- `Grant Application`: `search_fields: applicant_name,email`.
- `Volunteer`: `search_fields: volunteer_name`.
- Already complete: Donation, Donation Campaign, Recurring Donation, Sponsor,
  Membership, NPO Recipient Selection.
  Prompt-/field-named masters need nothing (Chapter, Volunteer Type, …).
