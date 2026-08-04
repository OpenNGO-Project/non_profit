# Non Profit - Documentation

## Purpose

`non_profit` is this bench's shared NPO domain app. It is a hard fork of Frappe's Non Profit app with Swiss fundraising additions and membership changes used by `ilanga_app`, `miki_app`, and Goodvantage apps.

## Important Consumers

| App | Dependency |
|---|---|
| `ilanga_app` | Lowercase `ilanga` presentation and editable Builder website through `good_npo`. |
| `miki_app` | Membership/Customer substrate for kibesuisse declarations. |
| `good_npo` | Generic Goodvantage NPO presentation layer. |
| `good_demo` | Demo signup/reset layer that seeds non_profit demo records. |
| `good_direct_mail` | Postal campaigns consume canonical correspondence profiles and Household Donors without reversing the dependency. |
| `good_newsletter` | Optionally discovers saved NPO Recipient Selections through a provider hook; non_profit has no runtime import dependency on it. |

Breaking changes are allowed while Miki is not production, but `miki_app` must be updated in the same change whenever shared membership behavior changes.

The historical `PARTY_MODEL_REFACTOR_PLAN.md` (self-declared non-authoritative,
zero inbound references) was archived out of the repo in 16.7.0 to
`/workspace/development/archived/`. Its decisions that are still current were
ported into this document and `REQUIREMENTS.md` §4 before the move; everything
else described a Customer-regime redesign that was never shipped.

## Key DocTypes

- **Contact** is the canonical person identity; **Member**, individual **Donor**, and **Volunteer** are role projections that retain a conflict-checked canonical Contact link. One Contact can back at most one role of each type. Ordinary saves of existing roles cannot add, clear, or retarget that link.
- **NPO Organization** is the canonical organization identity anchor. ERPNext Customer and Supplier remain operating/accounting parties linked through hidden preparatory identity fields. NPO Organization is a legal-identity grouping only and is never a ledger party: several operating Customers (for example a parent and its branch) may share one legal identity without being merged, and verified-identifier uniqueness belongs to the NPO Organization rather than to any operating Customer. `legal_form` and identifiers owned by other apps are source evidence, not verified identity; base `non_profit` ships no country-specific identifier normalizer.
- **`Customer.npo_subject_type` is the authoritative NPO subject classification.** Code branches on it and never infers person/Household-ness from `customer_type`, name, address, or email. `Customer.npo_household` means "this Customer *is* the Household"; the legacy `Customer.household` means "this individual Customer *belongs to* a Household". The two must never be conflated — `household` is retired only once its social meaning has fully moved to Household Person rows. Supplier deliberately carries `npo_subject_type` / `npo_contact` / `npo_organization` but **no** `npo_household`.
- **Household** (with the **Household Person** child table) groups Contacts who share an address into one solicitation unit; see [Households](#households).
- **Donor**, **Donation**, **Donation Campaign**, **Recurring Donation**, and **Donation Tax Receipt** for fundraising. `Donor.customer` is the canonical ERPNext Customer relation for donor identity; Donation still links to Donor.
  Donation carries analysis dimensions `cost_center` (fetched from the campaign's cost center when empty) and `project` (both ERPNext doctypes) for downstream fundraising analytics (e.g. the `good_analytics` app).
- **Donation Tax Receipt** is the Swiss annual *Spendenbescheinigung*: one row per Donor, calendar tax year, and Company (unique index), holding the aggregated total, donation count, and the `{donation, date, amount}` detail list behind it. It is a plain (non-submittable) document whose `status` (Draft / Issued / Cancelled) can only be changed through `non_profit.non_profit.tax_receipts`; see [Donation Tax Receipts](#donation-tax-receipts). Since 16.10.0 it is the **single** Bescheinigung of the app — the older submittable `Donation Receipt` (+ `Donation Receipt Item`) was removed outright. It serves both dispatch paths: annual postal batches through `good_direct_mail`, and individual email issuance with the seeded `Spendenbescheinigung` PDF.
- **Sponsor**, **Sponsor Tier**, **Volunteer**, and **Grant Application** for broader NPO operations.
- **Non Profit Settings** for company, donor type, billing, invoicing, payment account, and email defaults.
- **NPO Recipient Selection** stores reusable channel-neutral Contact, Member,
  and Donor criteria for optional newsletter and direct-mail consumers.
- **Non Profit** Workspace and Workspace Sidebar for current Desk navigation,
  including Good Help, fundraising, Major Gifts, membership, community,
  Recipient Selections, settings, and the Expiring Memberships report. Contact,
  Address, Household, Customer, and Supplier are grouped together under
  **People**. The upstream links remain permission-filtered by Frappe; Non
  Profit roles do not gain broad access to those ERPNext masters.

## Households

**Household** groups people who share a postal address and are usually solicited
together. Its **Household Person** rows carry `contact`, optional
`relationship`, `from_date`, `to_date`, and `is_primary`. A row without
`to_date` is current. Normal move-out/divorce handling sets `to_date` instead
of deleting the row so the child table remains the dated history.

`from_date` is mandatory and `to_date` cannot precede it. Validation rejects a
duplicate current row for one Contact, more than one current primary, a second
current Household for the same Contact, and a Contact explicitly classified as
`Generic Endpoint`. Blank legacy Contact classifications are set to `Person`.
A Contact already used by a canonical person role or Household row cannot later
be reclassified as a Generic Endpoint. Household save and delete operations
both require write permission on every affected Contact unless a trusted caller
explicitly bypasses permissions. Mutations lock affected Contact rows deterministically before checking
conflicting Household Person rows.

`Household.on_update` projects the current Household onto every Member and Donor
whose hidden canonical `contact` field matches. It uses `frappe.db.set_value`
instead of saving role documents and refreshes
`Membership.is_household_membership`. Saved and prior rows are reconciled, so a
correction that removes or retargets a row and a Household deletion cannot leave
stale role links. Attaching an existing role to a Contact invokes the same sync
immediately. Member/Donor controllers also restore their read-only derived
`household` field on save.

The canonical service is
`non_profit.non_profit.doctype.household.household.add_person_to_household(household, contact, from_date, to_date=None, is_primary=False, relationship=None, *, ignore_permissions=False) -> Household`.
It requires write permission on Household and Contact unless a trusted
server-side caller passes `ignore_permissions=True`.

`Customer.household` and `Contact.title` remain operational custom fields.
Stage 1 also ships hidden, read-only identity preparation fields on Contact,
Customer, and Supplier, plus the **NPO Organization** master. These fields are
installed on both install and migrate; setup repairs partial metadata/schema
states where a Custom Field record exists but its database column does not.
All setup-owned Custom Fields carry module `Non Profit`, so uninstall removes
their links before dropping app DocTypes such as NPO Organization.
Addresses and Contacts attach to Household through standard Dynamic Links.
`Household Person` replaces `Household Member` through ordered migration
patches. Before model sync, each old Member/Donor row must resolve to exactly
one canonical Contact. The patch backfills the role's canonical Contact,
coalesces only exact same-Household/current-date rows for one person (the common
Member+Donor projection case), and renames the child DocType/table without
recreating it. Orphan child rows, invalid dates/primaries, missing roles,
no/multiple/conflicting Contacts, non-person identity classifications, and
conflicting current Household dates stop the migration before conversion
instead of dropping or guessing data. After model
sync, a second patch installs the required standard-master identity fields,
classifies migrated Contacts as people, and refreshes role/Membership
projections. Both patches are idempotent, including recovery after the
DocType/table rename has committed. If orphan cleanup already removed the old
DocType metadata but retained a populated `tabHousehold Member`, the pre-model
patch validates and copies those rows into an already-synced Household Person
table while retaining the orphan table as a recovery backup.

## Correspondence Profiles

`Contact.preferred_language` is an editable setup-owned Custom Field (Link to
Language), and `Household.preferred_language` is a normal Household Link field.
Neither has a default: unresolved language remains visible to the consuming
workflow instead of silently assuming a language.

`non_profit.non_profit.correspondence` is the generic, non-whitelisted
identity boundary for postal correspondence. It does not import or depend on a
campaign app. Public functions are:

- `get_correspondence_profile(source_doctype, source_name)` for one source. Its
  canonical-subject keyword form (`canonical_subject_type`,
  `canonical_subject`, and optional `contacts`, `members`, `donors`, and
  `customers` name lists) is the adapter for a consumer that already consolidated
  its audience; `as_of` is accepted as upstream selection context but does not
  redefine current Household rows.
- `get_correspondence_profiles(source_references)` for at most 500
  references, returned in input order. Existing `{doctype, name}` /
  `{reference_doctype, reference_name}` mappings and `(doctype, name)` pairs are
  supported. A canonical reference is a mapping with `canonical_subject_type`,
  `canonical_subject`, and optional `contacts`, `members`, `donors`, and
  `customers` sequences. Canonical aliases `Person` and `Organization` normalize
  to Contact and Customer. Across one call, at most 5,000 related identities may
  be supplied. Strings/bytes and mappings are rejected where a sequence is
  required, and iterable limits are checked after consuming only the allowed
  bound plus one item.

Supported sources are Contact, Member, Donor, Household, and Customer. The
service resolves each to a canonical `Person` (Contact), `Organization`
(Customer), or `Household`; a person's current Household is returned as context
but does not automatically replace that Person as the canonical subject. This
allows a Direct Mail consumer to consolidate only when its selected population
contains at least two current people in the same explicit Household. A Contact
classified as `Generic Endpoint` is rejected whenever a source tries to use it
as a person. Blank legacy identity kinds are read as people without writing the
classification back.
For a canonical reference, related role rows enrich the profile but never change
the declared canonical Contact, Customer, or Household. Related Donor language,
related Customer language, related Contact language, Dynamic Links on all four
related identity types, and explicit Contact/Customer address pointers are
eligible. A related Member or Donor also exposes its backing Contact and Customer
to those lookups.

Current Household people are ordered primary first and then by Contact name.
Profiles expose structured people/name components and an addressee, plus a
resolved language and exact `{doctype, name, fieldname}` provenance. The
language precedence available in this substrate is current Household, source or
related Donor, backing or related Customer, then canonical/current or related
Contact. A campaign-level
recipient override and run default remain consumer-owned fallbacks.

Active (`Address.disabled = 0`) Addresses are collected set-based from standard
Dynamic Links and explicit Contact/Customer address pointers. Candidates are
deduplicated, retain every `{doctype, name, via}` provenance path, and contain
structured postal fields. One resolved candidate is exposed as `address`; zero
adds `MISSING_ADDRESS`. With multiple candidates, one unique direct
Contact/Customer pointer or one uniquely primary Address is accepted; otherwise
the profile adds `AMBIGUOUS_ADDRESS` without selecting the first row. Other
stable issue codes cover missing/ambiguous canonical Contacts,
Households, Household people, language, and addressee. The complete public set
is `MISSING_CANONICAL_SUBJECT`, `MISSING_PERSON_CONTACT`,
`AMBIGUOUS_PERSON_CONTACT`, `MISSING_ORGANIZATION`, `MISSING_HOUSEHOLD`,
`AMBIGUOUS_HOUSEHOLD`, `MISSING_HOUSEHOLD_PEOPLE`,
`UNSUPPORTED_SUBJECT_TYPE`, `MISSING_ADDRESSEE`, `MISSING_LANGUAGE`,
`MISSING_ADDRESS`, and `AMBIGUOUS_ADDRESS` (also exported as
`CORRESPONDENCE_ISSUE_CODES`). Both `issues` (with details) and ordered
`issue_codes` are returned. Resolution performs reads only: it does not
classify Contacts, select/write an Address, or create party data.
The resolved structured Address is returned as `address`, with its document name
also available as `address_name` for consumers that already loaded Address rows.
Dynamic Link reads use one bounded query per target DocType with only that
DocType's exact target names. They therefore cannot trip the related-row guard on
false combinations produced by independent cross-DocType/name `IN` filters.

Household payment attribution continues through the existing Donor model. The
public server-side helper
`non_profit.non_profit.doctype.donor.donor.get_or_create_donor_for_household(household, donor_type=None, *, ignore_permissions=False)`
locks only the Household parent row before lookup, rejects multiple candidates,
reuses one canonical Household-subject Donor or one legacy row whose
`subject_type` is blank but whose `subject_household` is set, or creates one
named from `Household.household_name` with
`subject_type = "Household"` and `subject_household` set. Donor currently has no
inactive lifecycle state, so every persisted matching Donor is active for this
check. The helper deliberately creates neither a Household Customer nor another
identity DocType.

## Saved Recipient Selections

`NPO Recipient Selection` is a normal parent DocType in module **Non Profit**,
named by its unique, non-renamable `selection_name`. Campaign providers persist
that stable key. System Manager and Non Profit Manager have
full permissions; Non Profit Member has none. At least one channel and one source
must be enabled, and Member selection requires `membership_active_on` (metadata
defaults: Membership Status `Current`, active date `Today`). Saving evaluates
the current source union and stores the unique canonical `candidate_count` plus
`last_evaluated_on`. Those fields are an evaluation snapshot, not a live counter.

The public internal contracts in
`non_profit.non_profit.recipient_selection` are:

- `get_recipient_selection_rows(selection, channel)` accepts a saved name or an
  already-loaded document. Loading by name checks selection read permission. It
  validates `enabled`, channel `newsletter` / `direct_mail`, the selection
  contract, and read permission for every enabled source (`Contact`; both
  `Member` and `Membership`; or `Donor`). Source and canonical-identity queries
  apply normal row-level permissions, and evaluation fails closed above 10,000
  raw source rows. It returns deterministic raw source
  dictionaries with `canonical_subject_type`, `canonical_subject`, `label`,
  `source_doctype`, `source_name`, and available `membership`, `contact`,
  `member`, `customer`, `donor`, and `identity_name` values. This shape is
  directly accepted by `good_direct_mail.services.preparation.merge_source_rows`.
- `get_recipient_selection_configuration(selection)` returns a stable,
  JSON-compatible mapping with `configuration_version = 1`, selection identity,
  enabled/channel flags, and every source criterion. Direct Mail can include
  this mapping in a preparation fingerprint so a filter change invalidates a
  snapshot even when the resulting identities happen to remain equal.
- `evaluate_recipient_selection(selection)` is the in-memory evaluator used by
  validation and read-only preview. It applies the same selection and source
  permission checks but deliberately has no enabled/channel gate, allowing a
  disabled definition to be saved and previewed safely.

Contact source rows include only blank legacy or explicit `Person`
`Contact.npo_identity_kind`; optional `contact_tag` matches an exact Contact
`Tag Link`. Member rows join `Membership -> Member`, apply selected status/type,
and require `from_date <= membership_active_on <= to_date` (open-ended `to_date`
qualifies). Contact is canonical when present; Organization uses Customer, blank
legacy subjects may use Customer, and an Individual missing Contact fails closed.
Donors apply optional Donor Type, use explicit Household subjects plus the
compatible blank-subject Household form, then an explicit Individual Contact;
Organization uses Customer and blank legacy subjects may use Contact or Customer,
while unsupported subjects fail closed even if stale Contact/Customer links remain. Rows
whose canonical identity is not permission-visible and canonical Contacts marked
`Generic Endpoint` are removed. Final raw ordering is canonical type/name,
source type/name, then Membership.

The optional hook is:

```python
good_newsletter_audience_providers = [
    "non_profit.non_profit.recipient_selection.newsletter_audience_provider",
]
```

Its provider key is `npo_recipient_selection`. Source discovery uses
permission-aware `frappe.get_list` and exposes only enabled records marked
available for newsletters. Member extraction calls the permission-gated service
again; it never trusts the earlier source list — a disabled selection, or one
whose `available_for_newsletter` flag is off, is refused there as well.

Each row carries `email`, optional `contact`, `first_name`, `last_name`, the
complete `salutation` (`Guten Tag …` / `Bonjour …,`), and `language`, matching
good_newsletter's contact-aware provider contract. A candidate that resolves to
no reachable address keeps its row with an empty `email`; good_newsletter counts
those as `skipped_no_email` in the import summary rather than silently losing
them. good_newsletter creates the resulting subscribers through
`initialize_as_confirmed_import` (trusted existing-relationship import); the
provider only supplies rows and never writes consent state.

Canonical candidates are enriched through
`correspondence.get_correspondence_profiles` in batches of no more than 500
canonical candidates and 5,000 related Contact/Member/Donor/Customer names.
Selection consumers enable its permission-aware mode, which filters every
related Contact, Customer, Household, and Address before it can influence the
resolved addressee, language, email, or postal state.
Contact and Customer email fields are then loaded set-wise. A Contact candidate
uses its primary `Contact.email_id`. An Organization Customer candidate uses
`Customer.email_id` first, but only attributes it to a person Contact when that
Contact carries the same email; unrelated or Generic Endpoint primary Contacts
are not exposed. A matching unsubscribed Contact or inaccessible related Contact
rejects that Customer address; the resolver may then use a different eligible
person Contact email. Customer and Contact fields are permission-filtered in
complete 500-name queries, so large related sets are neither truncated nor read
one row at a time. It then checks the profile's deterministic primary/linked person
Contacts. A Household uses current Household Person contacts in profile
order (primary first, then Contact name). An email selected through an
unsubscribed Contact is excluded, and final email addresses are deduplicated
case-insensitively in canonical-candidate order.

Provider rows contain `email`, `contact`, `first_name`, `last_name`, complete
gender-neutral `salutation`, and `language`. Correspondence language variants
normalize to Good Newsletter's supported `de` / `fr` / `it` / `en`; unsupported
or missing values remain blank so the target Audience applies its configured
default. The complete neutral salutation uses the same default German greeting
when language is blank, matching Good Newsletter's default Audience language,
without inventing a stored language on the source identity.

The typed, GET-only `preview_recipient_selection(selection)` endpoint checks
selection and source permissions, counts the complete canonical union, and
enriches only its first 50 deterministic candidates. Each row contains subject
type/name, label, email, language, and `postal_ready`; structured postal fields
never cross the endpoint. `postal_ready` means correspondence resolved one active
Address containing address line, postal code, city, and country.

The form script uses the Actions menu. Every action rejects a dirty form so it
cannot evaluate or materialize stale persisted criteria. Preview is available on
every saved selection. Newsletter campaign creation is shown only for an enabled Newsletter
channel and create permission on both optional Good Newsletter Campaign and
Audience DocTypes; it invokes
`good_newsletter.api.campaign.create_from_source` with provider
`npo_recipient_selection`. Direct Mail routing is shown only for its enabled
channel and Good Direct Mail Campaign create permission; `frappe.new_doc` receives
only `recipient_selection` and `title`, so no server dependency is introduced.

## Donation Tax Receipts

`Donation Tax Receipt` is the app's **single** Bescheinigung. The legacy
submittable `Donation Receipt` (+ child `Donation Receipt Item`) was a second
Bescheinigung model and was removed outright in 16.10.0 (operator decision,
2026-07-31; `LETTER_DISPATCH_CONVERGENCE_PLAN_2026-07-31.md` Phase 2b). The
migrate patch `non_profit.patches.drop_legacy_donation_receipt` runs before
model sync and drops the leftover DocType rows, Print Formats, and tables while
the retired metadata is still available. The retired `NPO-DRCPT-`
naming-series prefix must not be reused.

Do not confuse it with a **Verdankung** (per-donation thank-you). That is a
different document: `Donation.thank_you_sent` covers today's immediate
thank-you, and a dedicated `Donation Acknowledgement` is planned as Phase 5 of
the convergence plan. A Verdankung never issues a Bescheinigung.

`non_profit/non_profit/tax_receipts.py` owns the Spendenbescheinigung business
rules; `good_direct_mail` produces and dispatches the postal letters. non_profit
never imports `good_direct_mail` at module level — the one call into it is
resolved with `frappe.get_attr`, and `create_receipt_campaign` fails with a clear
message when the app is not installed.

Names come from controller `autoname()` using
`make_autoname(f"NPO-STR-{tax_year}-.#####")`; the creation-year `{YYYY}` token
is deliberately not used, so historical runs carry their actual tax year.

Fields beyond the aggregation payload: `language` (Select `de`/`fr`/`it`/`en`,
default `de`) records the correspondence language for the letter and the email;
`email_sent_on` (Datetime, read-only) is the individual-issuance audit stamp;
`remarks` is free text rendered into the print format. `cancelled_on`,
`cancelled_by`, and `cancellation_reason` are immutable service audit fields.

### Two dispatch paths

1. **Annual postal batch** — `generate_receipts` → review Drafts →
   `create_receipt_campaign` → prepare/freeze/generate/post in `good_direct_mail`
   → `mark_receipts_issued` with the exact posted names where available.
2. **Individual email issuance** — `send_receipt_email(receipt)` sends the
   seeded `Spendenbescheinigung` PDF to one donor. This is the path ported from
   the retired `Donation Receipt.send_to_donor()`.

- `generate_receipts(company, tax_year) -> {created, updated, deleted, unchanged,
  stale_issued}` (whitelisted POST). Qualifying Donations are submitted
  (`docstatus 1`), paid (`paid = 1`), belong to the Company, fall inside the
  calendar year, have `amount > 0`, and name a Donor. The current user needs
  read/User Permission access to the Company, whose default currency must be
  CHF, plus Donation read and Donation Tax Receipt create/write/delete. The
  service first locks the existing Company row `FOR UPDATE`; this stable anchor
  exists even when no series/Donation/receipt row exists. It then performs
  permission-complete reads and deterministic locking re-reads of current
  Donations and receipts. Donations are grouped per Donor into one Draft
  receipt. Re-running is idempotent: unchanged receipts are left alone, changed
  Drafts are refreshed, Drafts with no remaining qualifying Donation are
  service-deleted and counted under `deleted`, Cancelled receipts are never
  revived, and every stale **Issued** receipt (including a donor absent from the
  current groups) is reported by name under `stale_issued` instead of being
  silently rewritten.
- `direct_mail_candidate_rows(reference) -> list[dict]` is the
  `good_direct_mail_audience_providers` implementation registered under the key
  `donation_tax_receipt`. `reference` is `"<company>|<tax_year>"`. It returns one
  row per **Draft** receipt, resolving the Donor's canonical postal subject
  with the same rules as `NPO Recipient Selection` (explicit/compatible Household
  first, then Contact, with the Organization/blank-legacy Customer fallback).
  Donors without a canonical subject are skipped and logged — direct mail can
  only address a canonical subject. Each row carries a `producer_context` of
  `tax_year`, `receipt_name`, `receipt_total` (`fmt_money`, CHF),
  `donation_count`, and `donation_table_html` — a server-built de-locale
  date/amount table. The `_html` suffix marks it as trusted markup in direct
  mail's freeze contract, so it is built here with escaped cell values and never
  from operator input.
- `create_receipt_campaign(company, tax_year, letter_head, print_format=None,
  title=None, body_html=None, company_address=None) -> str` (whitelisted POST,
  System Manager or Direct Mail Manager). It calls `generate_receipts` first,
  then `good_direct_mail.services.producers.create_producer_campaign` with
  letter category `Official`, no payment part, `manual_batch` dispatch, German
  main language, and one de language row (`title` / `body_html` override the
  German letter defaults; the Campaign itself is titled from Company and year).
  A second non-cancelled Campaign with the same provider/reference is rejected,
  preventing duplicate annual batches.
  `company_address` is required by the Campaign and is resolved from the
  Company's sole or uniquely primary active Address when not supplied.
- `mark_receipts_issued(company, tax_year, receipt_names=None) -> int`
  (whitelisted POST, same role gate) flips selected Draft receipts of that
  Company/year to Issued with `issued_on = today`. Explicit names represent the
  exact posted Campaign or individually delivered set. If omitted, names come
  from the Draft-only direct-mail provider, so subjectless drafts are not marked
  as mailed. Repeated calls skip already non-Draft names. Operators run it after
  delivery; driving it from a posting callback is a deliberate follow-up.
- `cancel_receipt(receipt, reason) -> {receipt, status, changed}` (whitelisted
  POST, same role gate) is the minimal correction flow. It enforces receipt
  write and Company read/User Permission, locks Company then receipt, moves a
  Draft or Issued receipt to Cancelled, and records immutable cancellation time,
  user, and required reason. Repeated calls preserve the original audit. A
  Cancelled unique donor/year/company record is not replaced automatically.
- `send_receipt_email(receipt) -> {receipt, email, print_format}` (whitelisted
  POST) is the individual-issuance path. It loads the receipt and requires both
  document `read` and the DocType `email` right — `run_doc_method`-style entry
  points only enforce read, and sending mail on behalf of the organisation plus
  stamping an audit field is more than a read. Only `Draft` or `Issued` receipts
  may be emailed. The donor address is resolved live through the canonical Donor
  chain (`get_donor_email`: canonical Contact → `Customer.email_id` → linked
  Contact → legacy), and a donor without any email produces a clear error rather
  than a silent no-op. The seeded `Spendenbescheinigung` Print Format is rendered
  to PDF with `frappe.attach_print(..., lang=receipt.language)` and handed to
  `non_profit.non_profit.mailer.send_referenced_email` with
  `reference_doctype`/`reference_name` set to the receipt. A registered
  downstream provider can therefore create a Communication on the receipt
  timeline; without one, delivery falls back to `frappe.sendmail`. Finally
  `email_sent_on` is stamped. **Emailing never changes the status** — `Issued` remains the explicit
  `mark_receipts_issued` action for the annual run, so a courtesy copy of a Draft
  does not pretend the batch went out. The Desk action lives in
  `doctype/donation_tax_receipt/donation_tax_receipt.js`
  ("Spendenbescheinigung per E-Mail senden").

All official generated receipt fields are protected by one module-private
service-write capability sentinel in the controller, the same pattern as
`good_direct_mail/services/guards.py`. Direct insertion is rejected, and updates
to donor/name, tax year, Company, currency, status, issue/cancellation/email
audit, totals, count, or details require the identity sentinel. A
request-supplied truthy flag cannot authorize a write. `language` and `remarks`
remain operator-editable. Direct deletion is also rejected; generation can
delete only a stale Draft through the same capability.

Open business questions (recorded in the bench-level
`LETTER_DISPATCH_CONVERGENCE_PLAN_2026-07-31.md` and **not** decided here):
further qualifying-donation refinements (minimum amounts, in-kind gifts,
membership fees), cantonal receipt format variations, and the signature image.

## Person-Level Contact Suppression

`NPO Contact Suppression` is a channel-neutral, person-level "never contact
this person" flag keyed by canonical Contact (the suite's shared person
identity — Members and Donors canonicalize to Contact first). Each row carries
a required scope (`Do Not Contact` or `Deceased`), an `active` check
(default on) so a mistaken row can be retired without deleting its history,
and an optional date and reason. Generic Endpoint Contacts are rejected —
they are not people. Permissions mirror `NPO Recipient Selection` (System
Manager and Non Profit Manager, full non-child access) and changes are
tracked.

`non_profit.non_profit.contact_suppression.active_suppressed_contacts(contact_names)`
is the single query seam for consumers: a trusted server-side read returning
the subset of the passed Contact names that hold any active suppression row,
chunked to 1,000 names per IN clause. Consuming campaign apps (postal or
email) call it inside their own eligibility pipelines as one ADDITIONAL
exclusion reason. It deliberately does not replace channel-owned
consent/suppression machinery, and non_profit itself imports no consumer app —
the helper is a neutral seam like the audience provider hooks.

## Hooks

- `after_install = non_profit.setup.setup_non_profit`
- `after_migrate = non_profit.setup.after_migrate` refreshes standard-master custom fields and fundraising fixtures.
- `before_uninstall = non_profit.setup.before_uninstall` clears this app's
  Workspace Sidebar ownership so developer-mode uninstall does not delete the
  shipped sidebar JSON.
- `before_tests = non_profit.non_profit.utils.before_tests` shortens the local
  in-process test URL, runs the setup wizard only on a site with no Company, and
  refreshes app-owned fundraising fixtures. It does not rename ERPNext records,
  delete Item Prices, or alter global Customer, Address, Fiscal Year, or Email
  Account data on an existing shared site.
- `good_newsletter_audience_providers` registers the optional
  `npo_recipient_selection` provider factory without importing Good Newsletter.
- `good_direct_mail_audience_providers` registers
  `non_profit.non_profit.tax_receipts.direct_mail_audience_provider`, whose
  descriptor maps the `donation_tax_receipt` key to `direct_mail_candidate_rows`.
  Only `good_direct_mail` reads the factory hook, so it is inert when that app is
  not installed.
- `non_profit_referenced_email_providers` (consumed by
  `non_profit.non_profit.mailer.send_referenced_email`) lets a private
  downstream app — usually good_npo via Good Connector's
  `send_referenced_email` — deliver the app's doc-referenced emails
  (Membership acknowledgement, Donation thank-you, Donation Tax Receipt
  send, Grant review invitation) with a Communication on the reference
  document's timeline. The last registered provider wins; with no provider
  the mailer falls back to plain `frappe.sendmail` with the same arguments.
  Provider errors propagate — no fallback re-send after a provider failure.
- `doc_events["Membership"]["validate"] = non_profit.non_profit.membership_sync.validate_no_overlap`
  blocks overlapping active Memberships by default. Callers can set
  `doc.flags.warn_on_membership_overlap = True` before validation when an
  overlap should be shown as a warning instead of a hard stop.
- `Donation Campaign` owns its Desk form chart in the DocType JS. The renderer
  clears existing chart sections before handling new unsaved forms or async
  refreshes, so stale data from another campaign cannot remain visible. It only
  removes its own `non-profit-campaign-chart-section` markup; presentation-app
  chart sections remain presentation-app-owned. The chart CSS keeps the axis,
  grid, and stacked bar tracks on one shared plot height, explicitly stretches
  the chart section/body to full available width, and uses shrinkable month
  columns so the form dashboard does not overflow horizontally on narrow Desk
  layouts. Changing the chart year keeps the existing chart in place while the
  new data loads and restores the mobile scroll position after replacement.
- Daily scheduler jobs expire memberships and process recurring donations.
- Recurring Donation processing creates submitted, unpaid Donation rows for due
  active schedules. It obtains the complete current schedule document in one
  locking read, checks that current state is still active and due, and performs
  a locking lookup before reusing or creating the installment for that
  schedule/date. It advances `next_date` at most once, cancels schedules that
  pass `end_date`, and commits or rolls back each schedule independently. A
  two-connection regression runs the real worker helper and proves that two due
  workers create one installment. The POST-only manual action also discards its
  caller's stale state and acts on the complete locking read.
- `Payment Entry` is extended through `doc_events` hooks, not
  `override_doctype_class`: the override resolves to the last installed app
  (hrms wins on this bench), while doc_events fire for every Payment Entry
  regardless of which controller class is active.

## Roles And Desk Access

`Non Profit Manager` and `Non Profit Member` are Desk roles in this bench. Install/migrate setup keeps them enabled with Desk Access and repairs existing users with either role that were left as Website Users. This prevents SSO-created NPO operators from having non_profit DocType permissions but failing Frappe's standard list helpers such as saved `List Filter` loading.

Non-profit setup also disables `auto_opt_in` on ERPNext's known loyalty test
fixtures (`Test Single Loyalty` and `Test Multiple Loyalty`) when they exist.
Those fixtures are created by ERPNext tests and match every Customer, which
otherwise makes normal NPO/Miki Customer saves show "Multiple Loyalty Programs
found" messages. Real Loyalty Program records are left untouched.

## Whitelisted API Contracts

Mutation endpoints must check permissions and let Frappe manage the request
transaction. The Spendenbescheinigung endpoints live in
`non_profit/non_profit/tax_receipts.py` and are documented under
[Donation Tax Receipts](#donation-tax-receipts): `generate_receipts`,
`create_receipt_campaign`, `mark_receipts_issued`, `cancel_receipt`, and
`send_receipt_email` are all POST-only and permission-gated, and none of them
uses `ignore_permissions` or commits inside a request or document hook.

Published Grant Application pages never render applicant email and apply
explicit HTML escaping to applicant-provided display values. Authenticated users
may still see the non-email contact section according to the existing page
contract.

### Receipt jurisdiction contract

There is one Bescheinigung and it is Swiss. Fundraising setup seeds the German
Print Format **Spendenbescheinigung** for `Donation Tax Receipt`: CHF amounts,
calendar tax year, itemized `donation_details` table, total, and the Swiss
confirmation wording ("Wir bestätigen, dass die aufgeführten Zuwendungen
eingegangen sind und ausschliesslich zur Förderung der steuerbefreiten
gemeinnützigen Zwecke unserer Organisation verwendet werden."). The header is
deliberately address-free: donor address and issuer identity come from the
Letter Head, exactly as in the retired `Donation Receipt DE` format whose German
layout and wording this format is based on.

The German income-tax paragraphs of `Donation Receipt DE` (`§ 10b EStG`,
`§ 5 KStG`, `§ 9 GewStG`) were **not** carried over — the app has always
rejected German legal wording on the Swiss send path, and the tax receipt is
CHF-only by construction. Deployments that need a legally reviewed local variant
edit the seeded format in place; once its HTML no longer matches a shipped hash
it is operator-owned and migrate never touches it again.

Fundraising setup inserts `Spendenbescheinigung` and `Donation Slip CH` when they
are missing. Existing Print Format HTML is treated as app-managed only when its
SHA-256 hash matches an append-only allowlist of shipped bodies. This content
ownership contract lets migrate apply a later shipped body to an untouched seed
without overwriting any operator-edited body; it does not require a custom field
on the core Print Format DocType. When shipped HTML changes, retain the prior
hash in the allowlist. The `Donation Thank You DE` Email Template has a separate
create-only contract and is never updated by migrate after insertion.

`get_campaign_donation_chart(campaign, year=None)` on the Donation Campaign
controller requires read permission on the Campaign and returns twelve monthly
buckets for submitted paid donations on that campaign in the selected year.
Segments are donation-level so the Desk form chart can open the underlying
Donation directly.
Donation Tax Receipt email issuance requires receipt read plus DocType email
permission; chapter staff edits and grant review invitations require write
permission on the target document. A logged-in portal
user may join a published Chapter only as themselves, and may leave only their
own active Chapter row; editing another user's Chapter row still requires
Chapter write permission. Member-supplied `website_url` values are restricted
to `http(s)://` URLs server-side, and the public chapter page escapes
member-supplied `website_url` / `introduction` values when rendering.

The development-only `Donation.mock_pay` endpoint is guest-whitelisted but
POST-only and inert unless both `developer_mode` and
`enable_non_profit_mock_payments` are set. It is not a production payment
confirmation path.

Public donation pages that delegate to `non_profit.www.donate._handle_submission`
must pass server-side validation for donor name, email syntax, an amount within
the shared public bounds (CHF 5–100'000), accepted consent, and allowed frequency
(`one_off`, `Monthly`, `Quarterly`, `Yearly`). The amount check rejects non-finite input explicitly: `float()`
accepts `inf`, `-inf`, `nan`, and overflowing literals such as `1e400`, and
`nan` compares False against every bound, so a positivity test alone cannot keep
those values out. `Donation.validate` repeats the same invariant at controller
level so no write path — Desk, import, portal, or bank reconciliation — can
persist a non-finite or non-positive amount. Company is resolved server-side; a
selected or listed Donation Campaign must be active and backed by an enabled
leaf Cost Center belonging to that Company. That campaign/Company gate lives
once in `non_profit.non_profit.campaign_gate.campaign_matches_company()` and is
shared with Good NPO's public checkout, so the two guest surfaces cannot drift
apart on a security boundary; ownership is derived from the campaign's Cost
Center, never from the campaign name or historical Donations. Before any Donor/Customer lookup or creation, the normalized email
acquires the same hashed `Individual` identity lock used by guided and Good NPO
Member flows through transaction completion. Browser `required` attributes are
UX only. The handler is rate-limited. Every guest submission must include a
valid GoodVantage CAPTCHA response. Missing Good Connector or missing/unreadable
CAPTCHA configuration fails closed; the app can still be installed without Good
Connector, but public donation submission is unavailable until CAPTCHA support
is installed and configured. The submit control starts disabled and follows the
shared loader's `data-load-state`; server verification remains authoritative.

The base public page and confirmation label amounts as EUR, and the seeded
`Donation Thank You DE` template formats EUR. The separate `Donation Slip CH`
format displays CHF. Donation has no currency field, so these are presentation
assumptions, not a company-derived currency contract. Production sites must
provide one approved currency-aware presentation flow.

The `donate_confirm` page is key-gated: every Donation gets a random
`confirmation_key` on insert (`Donation.before_insert`), the donate flow
redirects with `?donation=<name>&key=<key>`
(`non_profit.www.donate.donation_confirm_query`), and the page refuses to
disclose donor name or amount without a matching key — Donation names are a
sequential series, so the name alone must not unlock the page. Logged-in users
with Donation read permission can still open the page without a key. Pages that
build their own confirm redirect must use `donation_confirm_query()`.
Donations created before the field existed have no key and are therefore not
guest-viewable.

## Donation Thank-Yous

Donor identity mirrors the Member/Customer pattern: `Donation.donor` points to a
Donor, and Customer-level CRM data resolves through `Donation.donor ->
Donor.customer`. Donor no longer stores its own email address; an individual
Donor reads email from its canonical Contact first, while organization and
legacy roles fall back to `Donor.customer -> Customer.email_id` and then a
linked Contact. The result is copied onto Donation /
Recurring Donation rows as an operational snapshot.
`Donor.preferred_language` is a Link field to
Frappe's `Language` DocType, matching core language selectors such as
`User.language`; stored values remain language codes like `de` or `en`.
`Donor.make_customer_and_link()` and
`non_profit.non_profit.doctype.donor.donor.get_or_create_customer_for_donor()`
reuse a Customer from a same-email Member first, then a same-email Customer, and
otherwise create a new Customer. The helper links Contact and Address rows to
both Donor and Customer. A one-time migrate patch preserves existing
`Donor.email` values by creating/linking Customers before the Donor email field
is removed from the model. The patch runs after DocType model sync so fresh
installs have the newer `Donor.customer` column before it queries donor rows;
`backfill_donor_customers(limit=None)` remains available for explicit repair
runs.

`non_profit.non_profit.donor_identity.resolve_donor_customer_identity()` is the
policy-capable orchestration service for public/presentation callers. Non Profit
owns email normalization, Member-aware Customer lookup, Donor/Customer linking,
and Contact/Address continuity; callers provide only presentation values,
existing-Donor handling, insertion strategy, and ambiguity policy. Good NPO uses
safe rejection: when more than one Donor or Customer resolves to an email, staff
must resolve the identity instead of a guest request choosing one arbitrarily.
The older `find_donor_by_email()` and `get_or_create_customer_for_donor()`
dotted paths remain supported.

Desk creation helpers for Member, Donor, and Sponsor accept Contact-only,
Customer-only, or Contact+Customer selections. The Member list uses Frappe's
native `listview_settings.primary_action` hook to open a guided **Create Member**
dialog directly; each Add action creates a fresh dialog, and cancelling it leaves
the user on the list instead of an unsaved Member form. The guided dialog accepts
an Individual or Organization plus Membership Type and From Date. Individual
fields cover first/last name, email, optional phone, and complete postal address;
Organization needs a name and may include a complete address and a real named
human contact person. Country defaults from the site. It posts to the existing
`create_member_and_membership` endpoint using its additive guided input shape and
routes to the resulting Member. Calls using only the older `contact`, `customer`,
and `membership_type` arguments keep their existing behavior and response keys.
Optional Existing Contact and Existing Address selectors load those records into
read-only identity fields; server-side resolution treats the selected records as
authoritative, checks record permissions and person classification, and adds only
the missing role links. Leaving the selectors blank keeps exact automatic reuse.
On a site where Good Connector is not installed, the list action falls back to
the original technical Contact/Customer selector instead of offering raw identity
creation; this preserves the app's optional Connector dependency.

The guided endpoint is an authenticated Desk workflow, not a wrapper around the
Good NPO guest endpoint. Before writing, it requires create/read/write permission
on Contact, Address, Customer, Member, and Membership plus read access to the
selected Membership Type and Country. It lets Frappe own the request transaction,
does not commit, and does not create subscriptions, invoices, or emails. Good
Connector performs deterministic Contact and Address resolution. Exact canonical
person identity and exact linked addresses are reused; same-email Customer rows
alone are never authority to adopt or modify a Customer/Household. Multiple or
contradictory Contact, Member, Customer, organization-name, or exact Address
candidates stop with a staff-review message. Organization Customers may retain
an existing primary Contact while another real human correspondence Contact is
linked; the guided flow never replaces the existing primary.

Guided identity keys are transaction-scoped to serialize duplicate submissions,
and current parent-record reads are locked before mutation. Deadlocks are allowed
to propagate to Frappe after MariaDB rolls back the transaction rather than being
masked by an invalid savepoint rollback. When an exact Address is reused, values
the concise dialog does not collect (such as address line 2, canton/state, email,
phone, and its existing title) are preserved.

One request-scoped registry renews its five-minute Redis identity-lock leases
every two minutes, revalidates every token immediately before commit, and
releases all locks after commit or rollback. Renewal stops after 30 minutes;
lease loss or that cap aborts commit and asks the caller to retry, while the
finite Redis TTL still recovers from worker/process failure. Lock keys contain a
hash of the normalized identity type/value rather than PII.

Individual creation stores the resolved person in `Member.contact`, links the
Address to Contact/Customer/Member, and reuses a Member only through that
canonical Contact. Same display names with different emails therefore remain
separate. Organization creation uses a Company/Partnership Customer and an
Organization Member whose canonical Contact stays empty. An optional contact
person is a separate Person Contact linked to the Organization Customer and
Member through Dynamic Links; the organization itself is never created as a
Contact. Organization addresses link to Customer and Member, not automatically
to the contact person's private identity. Address type `Billing` is operational
metadata and is not postal consent.
Contact-only individual Donors store the canonical `Donor.contact`, keep a
Contact Dynamic Link, and have no Customer until one is explicitly selected
through a creation/import/repair flow. Customer-only Company donors remain
Organization subjects backed by the Company Customer; their linked contact
people or generic mailboxes are correspondence links, not canonical person
identity.
Sponsor creation reuses the same Donor identity helper before creating/reusing
the Sponsor. Contact Dynamic Links are appended through the parent Contact
document, not inserted as standalone child rows. These helpers explicitly require
create permission for the target record plus write permission on selected
Contacts/Customers before they append links or update Customer/Donor identity
fields. Conflicting canonical or Dynamic-Link Contact assignments are rejected
instead of silently moving a Contact to another Donor/Member/Volunteer.
Person-role helpers classify blank
legacy Contacts as `Person` and reject an explicit `Generic Endpoint` rather
than silently reclassifying a shared mailbox. Volunteer creation intentionally
accepts Contact only, stores `Volunteer.contact`, and does not create a Customer.

`Donation.thank_you_sent` is a standard field on Donation for **Verdankungen**. `Donation.send_thank_you()` queues the configured Email Template, stores `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` when available, and marks this field once the email is queued. Presentation apps such as `ilanga_app` and `good_npo` read this field for pending thank-you queues. A Verdankung is not a Bescheinigung: an immediate thank-you never creates or touches a **Donation Tax Receipt**. A dedicated `Donation Acknowledgement` (Verdankung) document is planned as Phase 5 of `LETTER_DISPATCH_CONVERGENCE_PLAN_2026-07-31.md`; do not re-model it as a second Bescheinigung.

`Donation.on_payment_authorized()` is the authoritative payment state machine.
It ignores statuses other than `Authorized` / `Completed`, temporarily sets
`paid = 1`, then creates the
configured Payment Entry when automatic creation is enabled. If Payment Entry
creation or submission fails, the base controller resets `paid`, logs the
accounting error, and raises. Only after accounting succeeds does it call the
narrow `_dispatch_payment_thank_you()` policy seam; presentation extensions may
replace the message policy but do not override settlement. Donation itself owns
all `thank_you_sent*` audit writes through `_mark_thank_you_sent()`.
The `Payment Entry` delta is delivered through `doc_events` hooks
(`before_validate` / `validate` / on_submit / on_cancel / on_change registered
in `hooks.py`), not through
`override_doctype_class`. The override resolves to whichever app installed
last — on this bench `hrms` registers its own Payment Entry class, which made
non_profit's former controller override inert and broke Donation settlement.
doc_events fire for every Payment Entry regardless of the active controller,
so the Donation behaviour no longer depends on install order. The
`NonProfitPaymentEntry` class remains as an import-compatible shell only.
The early `before_validate` company check runs before an active controller
tries to resolve cross-company reference details; the full account and
allocation checks remain in `validate`.
Reference details and the Create Payment Entry helper expose only the Donation
amount not already allocated by submitted Payment Entries. Donation carries
two maintained read-only custom fields mirroring Sales Invoice semantics:
`grand_total` (set equal to `amount` on validate) and `advance_paid` (the sum
of submitted Payment Entry allocations, refreshed by the same sync path that
maintains `paid`, on Donation submit, and on Payment Entry submit/cancel;
existing rows are backfilled by patch). ERPNext's generic reference-details
fallback therefore computes `outstanding = grand_total - advance_paid`, which
is exactly the remaining Donation outstanding, so the active controller's
`validate` passes under erpnext base, hrms, or any future override winner.
A fully allocated Donation cannot create another Payment Entry. Final
submission locks all referenced Donation rows in name order and obtains complete
Donation amount/Company/Donor state, account configuration, and submitted
allocations through current locking reads. The prior-allocation query excludes
the current Payment Entry, and cumulative allocation above the current Donation
amount is rejected, so a REPEATABLE READ snapshot cannot let a waiting draft post
a second settlement. The two-connection regression submits both competing
Payment Entry drafts through normal `Payment Entry.submit()` lifecycle, proving
the installed controller and non_profit doc-events run rather than testing raw
row insertion. Donation references must use the Donation company and its expected Donor receivable account: the configured
Donation Debit Account when it belongs to that company, otherwise ERPNext's
company-specific Donor party account. Cancellation recalculates the paid flag
and `advance_paid` from the remaining submitted Payment Entries.
Bank reconciliation stays separate from payment success. `Donation.reconciled`,
`reconciled_on`, and `reconciled_payment_entry` are read-only mirrors of
submitted Donation Payment Entries whose `clearance_date` has been set by
ERPNext Bank Clearance or Bank Transaction reconciliation. For card providers,
payment success should submit the Payment Entry and mark the Donation paid;
later bank/payout import and matching sets the clearance date and therefore the
Donation reconciliation fields. The `Bank Transaction` override only syncs
Donation mirrors after ERPNext updates the linked Payment Entry; it does not
change ERPNext's bank reconciliation rules.
Global `Non Profit Settings` accounts are applied only when the configured
Account belongs to the Donation company, so one company's legacy settings do
not overwrite another company's party or bank accounts.

When Good Connector is installed, Donation submit stores a complete,
doctype-namespaced 27-digit QRR in `Donation.gc_qr_reference`, and migrate
backfills missing references on existing submitted Donations without changing
`modified`. Valid stored legacy references are never recomputed, preserving
already-issued payment slips. The Donation provider
registered through `good_connector_ebics_reconciliation_providers` performs
read-only matching by QRR, Donation/Bank Transaction company, company currency,
submitted state, and remaining outstanding. It returns every submitted same-QRR
Donation before amount checks so a duplicate identity cannot be selected by
amount, and it does so through a deterministic ordered read without provider-side
locking. A sole exact identity remains present but ineligible when policy blocks
automation, so another provider cannot silently win. It is eligible only when
the Company, receiving bank Account, and expected Donor receivable Account all
use the Bank Transaction currency; unsupported multi-currency cases stay for
manual review. The builder sets the Bank Transaction date before calculating
Payment Entry exchange values. Good Connector aggregates this with invoice and
other providers, locks the selected eligible target, and leaves multiple
aggregate candidates for manual review before voucher submission and Bank
Transaction linking.
QRR assignment locks the Company and rejects active same-company collisions
with both Donations and Sales Invoices before writing the reference.

### Donation Accounting Audit

The read-only bench helper below reports submitted Donation references whose
cumulative allocations exceed the Donation amount, whose Payment Entry company
differs from the Donation company, or whose Donor-side account differs from the
currently expected account:

```bash
bench --site development16.localhost execute non_profit.non_profit.custom_doctype.payment_entry.audit_donation_payment_entry_invariants
```

The helper is not whitelisted and does not update Donations, Payment Entries, or
ledger rows. Every result requires manual accounting review. Correct historical
entries through normal ERPNext cancellation/reversal and replacement workflows;
do not directly edit submitted Payment Entries or GL/Payment Ledger rows. Because
the account check uses current Donation/account configuration, confirm historical
configuration before deciding that a reported account difference needs reversal.

### Donation QR Slips

`Donation.before_print()` generates the Swiss QR-bill SVG in Python and stores
it on `doc.qr_bill_svg` for the seeded `Donation Slip CH` Print Format. The
Print Format only renders that prepared value; it must not call QR generators
from Jinja. The slip body renders first, and the QR-bill is placed at the bottom
of a separate final page so normal document footer behavior does not overlap the
payment part. Missing creditor configuration is reported before checking the
optional `qrbill` Python package, so setup errors remain visible even on CI
images that do not install the QR-bill dependency.

When the configured creditor account is a QR-IBAN and Good Connector is
installed, the qrbill renderer receives the Donation's shared QRR as
`reference_number`. Ordinary IBAN slips remain non-QRR. The qrbill renderer and
its Non Profit Settings creditor source remain separate from Good Connector's
chqr invoice renderer.

Note: this bench intentionally runs two Swiss QR-bill engines. non_profit's
`swiss_qrbill.py` (qrbill package, creditor from Non Profit Settings) renders
Donation slips, while `good_connector.qr_bill` (chqr package, creditor from
the Company bank account, with QRR/SCOR reference support) renders invoice
QR pages for miki_app / good_event / good_npo. They remain separate
payment-document implementations even though non_profit may optionally import
Good Connector integration services such as CAPTCHA and identity matching.
When changing payment-relevant QR behavior, check both engines.

## Membership Compatibility

Miki uses:

- `non_profit.non_profit.membership_sync.get_customer_for_membership`
- `non_profit.non_profit.membership_sync.list_customer_memberships`
- `non_profit.non_profit.doctype.member.member.get_or_create_member_for_customer`
- `non_profit.non_profit.doctype.member.member.get_or_create_member_for_contact`
- `non_profit.non_profit.doctype.member.member.create_member_and_membership`
- `non_profit.non_profit.doctype.member.member.get_or_create_membership_for_member`
- Member/Customer links through `Member.customer`
- `Membership.member` as the canonical membership link

Member no longer stores `membership_type`. Membership Type, Status, and validity
dates belong only to `Membership`; Contact is the canonical person identity and
Member is its membership role. `Member.contact` stores that canonical link,
while `Member.customer` remains the operating Customer relation for B2B flows;
the Contact Dynamic Link is retained for standard Frappe navigation.

`Membership.company` has been removed. It is not the member's
business/company relation, and any business organisation lookup should resolve
through
`Membership.member -> Member.customer -> Customer`.

Donor, Member, and Company records do not store PAN/tax-id details. The legacy
`Donor-pan_number` and `Member-pan_number` custom fields plus India-specific
80G certificate DocTypes are removed by migrate so that PAN data is not retained
as hidden database columns. Donation gateway note import also filters PAN/tax-id
keys before creating Donor comments.

The Member dashboard gets its Membership connection from the DocType `links`
table. It intentionally does not show Bank Account; bank details belong to the
linked ERPNext Customer, not directly to Member.

Member names are operator-editable. When `Member.member_name` is blank and a
Customer is linked, the controller fills it from `Customer.customer_name` plus
`Customer.name_additional` when that field exists. Contact-only helper flows
derive the name from the Contact, persist `Member.contact`, and retain the
Dynamic Link row.
The Member Desk form does not write membership validity dates back onto Member;
if a legacy `membership_expiry_date` field exists, the client refreshes it from
the linked Membership without marking the form dirty.
The legacy manual `Membership.generate_invoice()` path requires the legacy
`Membership.invoice` link field and is not exposed when that field is absent.
Current app-specific membership billing should link Sales Invoices through the
presentation app's own fields, for example `Sales Invoice.good_npo_membership`.
Legacy Membership invoice/Payment Entry implementations and Donation
gateway-object helpers now live in `non_profit.non_profit.legacy_payments`.
Their historical controller/module dotted paths remain thin compatibility
facades and emit warnings through the `non_profit.compatibility` logger. Do not
remove those facades earlier than 90 days after warning telemetry is deployed,
and then only after one complete release cycle reports zero calls. New
integrations must use current Sales Invoice, Subscription, Payment Entry, and
Donation authorization services.
The legacy Contact/Customer helper accepts Contact, Customer, or both, creates or
reuses the Member first, links the Contact to both Member and Customer when both
are selected, then creates or reuses an open-ended Membership for the selected
Membership Type; presentation apps such as `miki_app` use this for parent-owned
business memberships. The guided raw-data Desk input mode is additive on the
same endpoint and does not change the original arguments or response keys.

If any of these contracts change, adjust `miki_app` and run its membership-related tests.

The **Expiring Memberships** report derives one row per Member from the latest
non-cancelled Membership (`MAX(to_date)`) and filters that date against the
selected month/fiscal year. Frappe v16 removed the old `Membership.paid`
assumption from this fork, so report queries must not reference it.

Memberships can be open-ended: callers that intentionally want no expiry set
`membership.flags.keep_to_date_open = True` before insert. This bypasses the
default billing-cycle `to_date` fill in the Membership controller. The fieldname
remains `to_date`; its Desk label is **Membership Until**.

Recurring billing is opt-in per **Membership Type** with the **Is
Subscription** checkbox. Leave it disabled for declaration or data-collection
flows such as MiKi, where billing is triggered by a later process after
customer data has been collected. The shared
`non_profit.non_profit.membership_subscription.ensure_membership_subscription`
helper returns without creating anything unless the Membership Type is marked as
a subscription. For subscription-enabled types, it creates or reuses an ERPNext
**Subscription Plan**, creates an open-ended ERPNext **Subscription** for the
linked Customer using **Non Profit Settings -> Company** as the accounting
company unless an explicit company argument is passed, writes
`Membership.subscription`, and clears
`Membership.to_date` when requested. Presentation apps such as `good_npo`
should call this helper instead of creating Subscription rows locally.

Payment-provider integrations are intentionally outside `non_profit`. Gateway
apps such as `payrexx_integration` should verify provider callbacks and then
call the standard document hooks (`Donation.on_payment_authorized`,
Membership/Sales Invoice/Subscription helpers) instead of adding
provider-specific settings or webhook endpoints here.
The old public mock payment helper is guarded by `developer_mode` plus the
explicit `enable_non_profit_mock_payments` site-config flag and must not be
used as a production payment confirmation path.

When `good_connector` is installed, legacy Member registration uses
`good_connector.identity_matching` to create or reuse the linked Contact for the
generated Customer/Member. Exact email/name matches are reused, ambiguous data
creates a fresh Contact, and fuzzy matches are sent to the shared duplicate
review queue instead of being merged automatically. The import is optional so
the fork remains installable without Good Connector in upstream-style benches.

## Major Gifts

Major-donor cultivation lives here as generic substrate (logic in
`non_profit/non_profit/major_gifts.py`).

DocTypes:

- **Major Gift** — one cultivation opportunity ("ask") per record. `stage`
  drives the pipeline (Identification → Qualification → Cultivation →
  Solicitation → Stewardship, plus terminal **Won** / **Lost**) and is the
  Kanban field. `ask_amount` / `expected_amount` / `probability` produce a
  read-only `weighted_amount`; entering a terminal stage stamps `outcome` and
  `closed_on` and forces probability (Won = 100, Lost = 0). `closed_amount` is
  the sum of submitted, paid Donations linked back through `Donation.major_gift`.
  Not submittable.
- **Donor Interaction** — a touchpoint ("move": Call / Meeting / Email /
  Letter / Event / Proposal / Note / Other) linked to a Donor and an optional
  Major Gift. On save/trash it refreshes `Donor.last_interaction_date` and
  `Major Gift.last_interaction_date` to the latest interaction. A linked Major
  Gift (on either Donation or Donor Interaction) must belong to the same Donor.

### Pipeline Workflow

A **Major Gift Pipeline** Workflow (built by `major_gifts.ensure_major_gift_workflow`
on `after_migrate`) drives the `stage` field. It is code-owned:

- **States** are the seven `stage` values (Identification, Qualification,
  Cultivation, Solicitation, Stewardship, Won, Lost), all at `doc_status = 0`
  (Major Gift is not submittable).
- **Transitions** advance one step down the pipeline (Qualify → Cultivate →
  Solicit → Move to Stewardship), plus **Mark Won** (from Cultivation /
  Solicitation / Stewardship), **Mark Lost** (from *any* open stage, so an early
  prospect can be disqualified without routing through Cultivation), and
  **Reopen** (Won → Stewardship, Lost → Qualification).
- **Single role.** Every transition is gated to one role — the first of
  `Non Profit Manager`, `System Manager` that exists on the site — with
  `allow_self_approval`. Administrator bypasses role checks, so seeding/tests
  still walk the pipeline.

The definition is **hash-stamped** (`WORKFLOW_VERSION_KEY` global default): the
Workflow is rebuilt only when the shipped states/transitions/role change, so a
migrate never reverts operator edits (roles, extra transitions, `is_active=0`).
When the optional `workflow_visualizer` app is installed, setup also enables
**Visible on Doctype** for this Workflow. If Workflow Visualizer is installed
after Non Profit, Frappe calls `non_profit.setup.after_app_install` after the
visualizer has created its custom field, and the handler applies the opt-in
immediately. The handler reacts only to `workflow_visualizer`; it does not make
the app a required dependency. The opt-in checkbox is code-owned and repaired
on setup/migrate if cleared. This does not rebuild or overwrite the Workflow's
operator-edited roles, transitions, active state, or other fields.

`major_gifts.advance_major_gift_to_stage(doc, target_stage)` moves a gift
forward programmatically. Because the active Workflow rejects backward moves, it
computes the shortest **forward** path (derived from the transition graph,
excluding Reopen) from the gift's *current* stage and saves one legal
single-step transition at a time — safe to call on a gift already partway
through the pipeline.

### Next Actions (linked Tasks)

A "next action" on a Major Gift or Donor Interaction is a real ERPNext **Task**,
not free text. Logic lives in `non_profit/non_profit/next_actions.py`. Each Task
back-links to its parent through the `Task.major_gift` / `Task.donor_interaction`
custom fields (added in `non_profit.setup.get_custom_fields`, created on
install/migrate). A Task created from a Donor Interaction that belongs to a Major
Gift sets both links, so it also surfaces on the gift.

The parents' `next_action` (Small Text), `next_action_date` (Date), and
`next_action_task` (Link → Task) fields are **read-only and derived** from the
earliest *open* linked Task (`status not in Completed/Cancelled/Template`,
ordered by `exp_end_date`). They are recomputed by `refresh_next_action`, which
runs from `set_next_action` and from the `Task` `on_update`/`on_trash` doc_event
(`on_task_change`) — so completing or rescheduling a Task updates the rollup.
Keeping the `next_action*` fieldnames means the pipeline list and reports keep
working off them.

Operators use **Actions → Set Next Action** on either form (whitelisted
`non_profit.non_profit.next_actions.set_next_action`, gated by parent write
permission): it prompts for the action, due date, and assignee (defaulting to the
gift's `relationship_manager` / interaction's `staff`), then creates, assigns
(standard Frappe assignment), and links the Task. The form **Connections** tab
lists all linked Tasks. The `convert_next_actions_to_tasks` patch migrates any
pre-existing free-text `next_action` values into Tasks.

Donor gains `relationship_manager`, `donor_level`
(Prospect/Grassroots/Annual/Mid-Level/Major), `capacity_rating`, a read-only
`is_major_donor` flag, and hook-maintained giving roll-ups
(`total_lifetime_amount`, `gift_count`, `first_gift_date`, `last_gift_date`,
`last_gift_amount`, `largest_gift_amount`, `last_interaction_date`).

Roll-ups recompute from a Donation's `on_submit` / `on_cancel` / `on_trash`
(and after `on_payment_authorized`) via `major_gifts.on_donation_change`,
counting submitted, paid Donations — the same semantics as Donation Campaign
totals. `is_major_donor` is set when `donor_level == "Major"` or lifetime
giving reaches `Non Profit Settings.major_donor_threshold`. When a Donation's
`paid` flag flips through the Payment Entry flow (`custom_doctype/payment_entry.py`,
a `db.set_value` that fires no doc hooks), the donor + linked-gift roll-ups are
recomputed inline off that flag. A daily `major_gifts.reconcile_fundraising_rollups`
scheduler job rebuilds every Donor roll-up and Major Gift closed amount, so
out-of-band changes and edits to `major_donor_threshold` retro-apply. The
`backfill_major_gift_donor_rollups` patch (and
`major_gifts.recompute_all_donor_giving`) backfill existing donors. All-record
reconciliation uses grouped Donation aggregates plus a set-based latest-gift
lookup that preserves `date desc, modified desc`. It compares the desired values
with stored Donor/Major Gift fields and sends only changed rows through chunked
`frappe.db.bulk_update`; the single-record hook APIs remain the synchronous path
for individual Donation changes.

Non Profit Settings → **Major Gifts** adds `major_donor_threshold` (auto-flag).

## Help And Navigation

Markdown under `non_profit/fixtures/help/non_profit/` is discovered by Good
Help's installed-app scan and synced into editable Wiki Documents when
`good_help` is installed. The Workspace Sidebar links to
`/app/good-help?app=non_profit`; customer edits remain protected by Good Help's
installed-content hash.

The Workspace and Workspace Sidebar are both source fixtures. The sidebar uses
`app: "non_profit"`, `module: "Non Profit"`, and `standard: 1`; the
`before_uninstall` hook preserves its source file in developer mode. Both expose
the channel-neutral **Recipient Selections** section.

## Test Commands

```bash
cd frappe-bench
bench --site development16.localhost run-tests --app non_profit
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.household.test_household
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.major_gift.test_major_gift
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.donor_interaction.test_donor_interaction
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.donation.test_donation --test TestDonationPaymentEntryInvariants.test_two_connections_allow_exactly_one_full_allocation
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.recurring_donation.test_recurring_donation
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.npo_recipient_selection.test_npo_recipient_selection
bench --site development16.localhost run-tests --module non_profit.non_profit.test_tax_receipts
bench --site development16.localhost run-tests --module miki_app.tests.test_end_to_end
```

`non_profit.non_profit.utils.before_tests` uses a short in-process test host URL,
runs the setup wizard only when the site has no Company, and refreshes app-owned
fundraising fixtures. It deliberately does not rename ERPNext test Customers,
change Customer naming, pre-create shared Addresses/Fiscal Years/Email Accounts,
or delete Item Prices. Tests that need those records must create namespaced local
fixtures and restore any committed global state themselves. The Donation
allocation regression uses two real MariaDB connections to establish stale
REPEATABLE READ snapshots and verifies that exactly one full allocation commits.

CI runs the server suite with the declared ERPNext dependency. Focused setup
tests mock the optional Workflow Visualizer field and Frappe's late-install hook
to verify dispatch, missing-field behavior, and idempotent opt-in without
mutating the shared test site's schema. Workflow Visualizer is not listed in
`required_apps`. Good Connector remains optional. Its provider's review-only
candidate contract and uninstalled behavior are covered by non_profit's unit
tests, while connector-backed QRR registration tests run in authorized
integration environments where the coordinated Good Connector API is installed.
