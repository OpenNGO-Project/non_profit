# AGENTS.md - non_profit

Architecture decisions live in
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md). Keep that register
current when boundaries, dependencies, ownership, public contracts,
security/consistency models, or migration strategy change. Append a decision and
supersede old records rather than rewriting accepted history.

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
- Public display-name consumers use `non_profit.non_profit.utils.customer_display_name`
  and `contact_display_name`. Customer names join nonblank canonical/additional
  parts with ` - `; Contact names prefer `full_name`, then normalized first/last
  parts, then an explicit fallback or docname.
- Keep coordinated demo reset support app-neutral. Register only
  `demo_data_reset_declarations`, expose metadata from
  `non_profit.non_profit.demo_data_reset`, and do not import or name a private
  reset consumer. The declaration owns the complete marker-resettable Non Profit
  graph, captures exact Recurring Donation Installments, and clears only the two
  captured `next_action_task` reciprocal links declared in
  `cleanup_managed_links`. Cleanup must lock and revalidate the current owner/link
  before mutation; reassignment after capture fails closed.
- All custom DocTypes must have Python controllers.
- All new `@frappe.whitelist()` functions need type hints.
- Public guest donations require GoodVantage CAPTCHA and fail closed when Good
  Connector or its CAPTCHA configuration is unavailable. Do not restore the
  former optional/exception-swallowing bypass.
- Website User Donation fallback and deprecated gateway donor lookup must use
  the same ambiguity-rejecting Donor/Customer identity contract as `/donate`;
  never restore first-candidate email selection on a secondary intake path.
- The generic `/donate` handler must call
  `resolve_donor_customer_identity(..., ambiguous_email_policy="reject")` and
  must never restore first-match email lookup. Candidate lookup includes the
  canonical `Donor.contact -> Contact.email_id` path. Multiple Donors/Customers,
  or one Donor plus one Customer without an existing Donor-Customer link or an
  explicitly Person-classified Customer sharing the canonical Contact, fail
  neutrally before master/Donation mutation. Missing Donor Type setup also fails
  without provisioning configuration from the guest request.
  Ambiguity diagnostics use the app logger with no raw submitted email; do not
  use Error Log because its request metadata includes form values. Guest input
  may add a review Comment but must never rename an existing Donor.
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
  neutral hashed `identity-lock:v1:{sha256(type\nvalue)}` Redis namespace with
  compatible co-installed identity engines. Normalized public person emails use
  the shared semantic type `Contact Email`; leases renew while the transaction is
  open, are revalidated before commit, and release on commit or rollback. Keep
  renewal bounded and fail the transaction if ownership is lost. If restoring
  snapshot isolation fails, close the database session best-effort, log a
  secondary close failure, and preserve the original restore error. After the lock
  is acquired, ambiguity-sensitive Donor/Customer discovery must run in the
  short-lived current-read mode so an earlier MariaDB repeatable-read snapshot
  cannot hide a concurrently committed identity. Lock and compare the current
  candidate set; drift raises the neutral `IdentityCandidateDriftError`, which
  is both validation-safe at public boundaries and retryable for workers, so the
  caller reloads the complete transaction instead of using mixed snapshots.
  Current-lock the selected Donor document before returning or mutating it, and
  compare its current `customer` link with the snapshot before caller handlers
  or identity writes. Link drift retries the complete transaction so a stale
  Customer existence read can never replace a newly committed link.
  Keep the `Member.email_id`, `Customer.email_id`, and `Donor.customer` lookup
  indexes declared through DocType / Property Setter metadata so a later model
  sync cannot drop them. Non Profit owns a newly created Customer Property
  Setter or one explicitly assigned to module `Non Profit`; blank module is not
  ownership. Preserve a compatible operator/foreign/unassigned setter and fail
  setup rather than taking over a conflicting disable. Fresh install and migrate
  register portable, equivalent-column-aware index DDL only after successful
  setup commits. That callback uses a dedicated database connection whose
  commit cannot run callbacks from the install/migrate transaction.
- Donor-to-Customer continuity propagates every Donor-linked Address Dynamic
  Link, preserves an existing Customer primary Address, and selects a new
  primary only from a unique enabled primary or sole enabled Address. Never
  collapse ambiguity by child-row order or select a disabled Address. Customer
  creation must use a non-group Customer Group; `All Customer Groups` is not a
  valid fallback.
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
- CI runs on a **wizard-less** site, and `before_tests` owns the setup. Do not
  add an ERPNext setup-wizard call to `ci.yml`: the hook only sets the site up
  when no Company exists, so a wizard-built site skips it and then carries
  records that ERPNext's own test bootstrap collides with.
- Two collisions with ERPNext test fixtures are already handled here, and both
  presented as a wall of `setUpClass` errors that never named the cause:
  - the test Company uses abbreviation `FCL`. `WP` belongs to ERPNext's
    `Wind Power LLC` test record, and claiming it makes every later
    `make_test_records` call that reaches Company fail on "Abbreviation already
    used for another company".
  - `reserve_erpnext_standard_price_lists` seeds Standard Buying / Standard
    Selling as **INR** before the wizard. `erpnext.tests.utils` runs
    `BootStrapTestData()` at import time and de-duplicates on a filter that
    includes the currency, so on a non-INR site it does not recognise the
    site's own copies, inserts, and dies on a primary-key duplicate.
- Never hardcode a Country, Territory, or Customer Group name in a test.
  Resolve it from the site (`Selling Settings`, or the first non-group row).
  A hardcoded `Switzerland` passes only on a site whose wizard ran with that
  country.
- Skip on the site, not the import path. `find_spec("<app>")` proves only that
  the bench carries an app; the site under test may never have installed it,
  and then the DocTypes are missing while the guard reads as available.
- Fundraising setup owns the `Spendenbescheinigung` and `Donation Slip CH` Print
  Formats only while their HTML matches a known shipped hash. Keep the
  managed-hash allowlists append-only when changing shipped HTML so untouched
  rows upgrade; never add an operator-edited body to those allowlists.
  `Donation Thank You DE` remains create-only after first insertion. The
  Spendenbescheinigung format is Swiss/CHF: it carries the German layout and
  wording of the retired `Donation Receipt DE` but never its German income-tax
  paragraphs.

## Documentation Contract

This repo keeps five synchronized artifacts: `REQUIREMENTS.md` (what the app
must do), `ARCHITECTURE_DECISIONS.md` (why durable boundaries and contracts
exist), `DOCUMENTATION.md` (how it works), `HOW_TO.md` (operator procedures),
and the code. Record new or changed requirements in `REQUIREMENTS.md` and keep
all five in sync with every change.

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
- Keep newsletter salutations identity-kind safe and aligned with the shared
  greeting contract: organizations use their canonical Customer language ahead
  of a related Donor default and fixed legal-entity greetings, English
  people/Households use `Dear`, unsupported or blank language falls back to
  German, and a blank addressee has no dangling punctuation.
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
- Household giving roll-ups are owned here and use the deduplicated union of
  current person Donors plus the Household-subject Donor, on the submitted/paid
  Donation basis. They lock the Household and bounded identity rows, not every
  historical Donation; all qualifying-state writers run the same serialized
  recompute. Counts/dates span every qualifying gift, but monetary fields
  are populated only when every Donation Company resolves to one currency; mixed
  or unresolved currency leaves money blank and raises the review flag. Keep
  payment/cancellation and Household-row refresh paths in sync.
- `Recurring Donation Installment` is reconciliation evidence only. Never use it
  to call a provider or initiate a charge. Obsolete cadence expectations are
  retired, never deleted, and the first actual snapshot plus approved full
  accounting/provider reversal evidence are immutable and remain auditable.
  The 16.18.1 anchored-date repair may move complete accounting evidence from a
  cumulative-step legacy date to its unique cadence-ordinal anchored row. It
  retains the retired date row, validates every pair before writing, and fails
  closed on duplicate, conflicting, or partial evidence.
  Reconciliation runs against the current processing date, not a historical
  reversal date, and its horizon includes both `provider_next_payment` and a
  future local `next_date` before terminal/end-date caps. Natural end-date closure
  leaves the final generated installment active so it can settle or become missed.
  Reversal Selects retain explicit blank defaults. Migration cleanup may clear
  only the exact former Accounting / Payment Entry Cancellation defaults when
  reference, date, amount, and recorded-on evidence are all absent; partial and
  complete evidence must remain untouched. Currency zero is blank reversal
  amount, not evidence and not an immutable value; a real reversal requires a
  positive amount plus every other field, after which all reversal evidence is
  immutable.
  Direct insert/update/delete is capability-guarded; only deletion of the owning
  Recurring Donation may cascade through the guarded framework lifecycle.
  Full-reversal paths lock the schedule before the Donation. Accounting reversal
  additionally requires one persisted installment whose immutable actual snapshot
  proves that the Donation was fully settled, no submitted allocation, and
  cancelled allocations covering the complete Donation. Cancelling one leg of a
  concurrently full split settlement records reversal only when the final leg is
  cancelled; separate partial settle/cancel attempts never combine into evidence
  for a full settlement that did not occur. Only exact reversal replays are idempotent, and conflicting
  kind/reference/amount/date evidence fails closed.
  Terminal recurring states require immutable structured closure audit, while
  the first terminal transition stamps date and actor server-side,
  provider failure metadata remains separate. Closure Select fields must retain
  explicit blank defaults; migration cleanup may clear only the exact former
  first-option pair on non-terminal schedules and must never alter terminal rows.
  Provider cancellation must reconcile locally before external dispatch so a
  preflight failure cannot cancel remotely while local evidence is invalid.
- Tribute notification input is stored on Donation. Guest adapters may provide
  snapshots but must not create/mutate recipient Contact or Address masters, and
  fulfillment is an explicit staff action rather than a payment side effect.
  The action requires Donation write plus read access to linked recipient masters;
  insert/import callers cannot forge terminal fulfillment audit.
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
- `Recurring Donation Installment`: `title_field: recurring_donation`,
  `search_fields: recurring_donation,donation`.
- `Grant Application`: `search_fields: applicant_name,email`.
- `Volunteer`: `search_fields: volunteer_name`.
- Already complete: Donation, Donation Campaign, Recurring Donation, Sponsor,
  Membership, NPO Recipient Selection.
  Prompt-/field-named masters need nothing (Chapter, Volunteer Type, …).
