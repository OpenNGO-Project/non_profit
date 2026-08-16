# Non Profit - Documentation

Architecture decisions: [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).

## Purpose

`non_profit` is a reusable NPO domain app. It is a hard fork of Frappe's Non
Profit app with Swiss fundraising additions and membership changes consumed by
downstream site, presentation, analytics, and dispatch apps through neutral
DocTypes, services, and hooks. Current package version: `16.20.0`.

## Consumer Contract

Downstream apps may present, seed, analyze, or dispatch from this app's domain
records. Optional behavior crosses provider hooks; this public repository never
imports a private consumer. ERPNext remains the only required app.

Shared membership behavior is a downstream compatibility contract. Consumers
must be updated in the same change whenever that contract changes.

Two public formatting helpers keep identity labels consistent across controllers
and downstream consumers:

- `non_profit.non_profit.utils.customer_display_name(customer_name,
  name_additional=None, fallback=None)` strips each part, joins nonblank customer
  and additional names with ` - `, and uses `fallback` only when both are blank.
- `non_profit.non_profit.utils.contact_display_name(contact_row, fallback=None)`
  prefers stripped `full_name`, then joined first/last names, then the explicit
  fallback or the Contact docname.

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
- **Donor**, **Donation**, **Donation Campaign**, **Recurring Donation**, read-only **Recurring Donation Installment**, and **Donation Tax Receipt** for fundraising. `Donor.customer` is the canonical ERPNext Customer relation for donor identity; Donation still links to Donor.
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
Setup-owned Custom Fields carry module `Non Profit`, except for
`Contact.preferred_language` when the shared connector is installed. That app
claims the shared person-language field as module `Good Connector`; later
non_profit setup runs preserve the claim. A standalone non_profit install owns
the field as `Non Profit`, and connector uninstall hands ownership back before
its cleanup. This keeps either app's uninstall from deleting a field the other
still uses while preserving normal cleanup for the remaining Non Profit fields.
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

Household also carries a materialized giving summary: lifetime total, gift
count, first/last gift dates, last amount, and largest amount. Its population is
the set union of Donors backed by **current** Household People and the canonical
Household-subject Donor used for joint giving. The union prevents double
counting when one Donor is reachable by both paths. The basis is exactly
submitted, paid Donation (`docstatus = 1`, `paid = 1`), matching Donor roll-ups.
Every recompute locks the Household first and locks the bounded identity set,
but deliberately does not lock every historical Donation. Donation/payment
writers run the same Household-serialized recompute after changing qualifying
state, so the final writer repairs any concurrent snapshot without a broad lock.
Linking a historical Donor to a canonical Contact refreshes both its former
projected Household and its current Contact Household. Gift
count and dates remain meaningful across currencies. Monetary fields use
`giving_currency` only when every qualifying Donation Company resolves to one
common default currency; mixed or unresolved currency clears all money fields
and sets `giving_currency_conflict` for review. Donation/payment/cancellation
hooks, Household person changes, the daily fundraising reconciliation, and the
migration backfill refresh these fields in bounded Household batches.

## Correspondence Profiles

`Contact.preferred_language` is an editable setup-owned Custom Field (Link to
Language) with the shared ownership lifecycle described above, and
`Household.preferred_language` is a normal Household Link field. Neither has a
default: unresolved language remains visible to the consuming workflow instead
of silently assuming a language.

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
resolved language and exact `{doctype, name, fieldname}` provenance. Current
Household remains first. An Organization then uses its canonical/backing Customer
before source or related Donor, so a role's default cannot override the legal
entity's explicit language; other subjects keep Donor before Customer. Canonical,
current, or related Contact follows both. A campaign-level
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
- `donor_source_rows(donor_names)` and `newsletter_members_from_donors(...)`
  expose the same permission-aware canonical identity and newsletter delivery
  rules to optional source apps.

`non_profit.non_profit.channel_launch` owns the neutral source-form launcher.
Channel apps register factories through `non_profit_audience_channel_creators`;
each descriptor supplies a key/label plus dotted `launch_fields` and
`create_campaign` callables and may supply a channel-owned `is_available`
permission callback. The GET-only form endpoint filters channels by source and
user availability and allows only constrained Frappe field types. Required
channel fields become mandatory only while that channel is selected. The POST
endpoint invokes required source transforms first, then selected creators sequentially
in the request transaction with one title, optional Donation Campaign, and a
single SHA-256 fingerprint over the transformed saved source configuration plus
evaluated canonical rows. At least one ordinary campaign channel is required;
available channels come from the hook-driven registry
(`non_profit_recipient_selection_channels`, see REQ-NP-CHAN-01) joined with the
two built-ins; `non_profit.non_profit.channel_router` (REQ-NP-CHAN-02) is the
1:1 transactional counterpart reading `Donor.receipt_delivery`.
an infrastructure transform alone is not a valid launch. Optional source apps
register their validation and fingerprint
callbacks through `non_profit_audience_source_providers`; this public app does
not name or import them. Channel permissions and channel-specific policy remain
in the registering app.

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
complete `salutation`, and `language`, matching
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

Greeting rendering is identity-kind safe. Person and Household addressees use
`Guten Tag <name>`, `Bonjour <name>,`, `Buongiorno <name>,`, or
`Dear <name>,`. Organization candidates never address a legal entity as though
its organization name were a person; they use `Sehr geehrte Damen und Herren,`,
`Madame, Monsieur,`, `Gentili Signore e Signori,`, or `Dear Sir or Madam,`.
Their canonical Customer language wins over a related Donor's default language.
Unsupported and blank languages fall back to German. When a person/Household
addressee is blank, the renderer returns only the greeting and removes the comma
that would otherwise dangle after an empty name.

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

## Recurring Donation Reconciliation And Closure

`Recurring Donation Installment` is a read-only, service-owned audit row. It is
not an invoice, a provider request, or a charge instruction. Reconciliation
materializes cadence dates from `start_date` through the latest of the current
processing date, an explicit requested horizon, a reported provider next-payment
date, and a future local `next_date`, then caps that horizon by terminal closure
and `end_date`. A historical reversal date remains audit evidence and never
moves the reconciliation clock backward. It snapshots expected amount/currency, assigns an
exact-date Donation first, then assigns a late paid Donation to the latest
unfilled due expectation. Extra submitted paid Donations become `Unexpected`.
Only `docstatus = 1, paid = 1` establishes the first actual settlement; an unpaid
generated Donation may link to its expectation but never contributes actual
amount. Once established, the Donation/date/amount snapshot is immutable and is
not cleared when a Payment Entry cancellation later clears `Donation.paid`.

When cadence, start/end dates, or provider horizon remove a previously
materialized date, reconciliation sets `is_retired` and `retired_on` instead of
deleting the row. Retired dates leave active expected/missed/variance roll-ups,
but keep linked Donation, reversal, amount, and date evidence. A later schedule
change that makes the same date expected again reactivates the row.
The 16.18.1 anchored-date compatibility rebuild is one narrow exception to where
that evidence resides. For schedules persisted by the former cumulative stepping
algorithm (for example Jan 31, Feb 28, Mar 28), it pairs each legacy and anchored
date by cadence ordinal, never by nearest-date guessing. Before writing, it
requires one evidenced legacy source and at most one empty anchored target for
every pair, and validates a Donation assignment plus either no actual snapshot or
a complete positive actual snapshot and, when present, a matching complete
reversal snapshot. It then moves those fields to the anchored row while retaining
the retired legacy expected date and amount as cadence audit. Multiple sources or
targets, a non-empty target, and partial or malformed evidence fail before any row
changes. Once the source is clear and the
anchored row owns the snapshot, rerunning performs no remap. A uniquely scoped
controller capability permits only complete evidence removal from an already
retired source. The post-model
`repair_anchored_recurring_installment_evidence` patch reruns the bounded backfill
under these rules for sites that already recorded the original 16.18 backfill.
Direct insert/update/delete remains capability-guarded. Deleting the owning
Recurring Donation is the only normal cascade: its `on_trash` deletes installment
rows through the same guarded framework lifecycle before link validation.

Statuses are Expected, Settled, Missed, Variance, Unexpected, Reversed, and
Cancelled. Reversed is derived only from complete immutable source/kind/reference/
date/amount evidence written by the neutral full-reversal service. The Payment
Entry cancellation hook records accounting evidence before clearing paid;
authenticated providers may record a Full Refund or Chargeback through the same
public API. Donation cancellation, docstatus, partial refund, and dispute state
alone never manufacture a reversal. The reversal Source and Kind Selects carry
explicit blank defaults and blank first options so a new expectation has no
reversal evidence. A versioned post-model cleanup clears only the exact former
automatic `Accounting` / `Payment Entry Cancellation` pair when reference, date,
amount, and recorded-on evidence are all absent. It is idempotent and preserves
both partial review evidence and complete legitimate reversals. Currency stores
a blank reversal amount as zero; the controller treats that zero as absent and
allows the reversal service to replace it. Any partial evidence or nonpositive
amount fails validation. A finite positive amount plus every other reversal field
is complete evidence, and a source/kind-compatible complete reversal makes every
reversal field immutable. The same numeric rule lets reconciliation replace the
blank zero `actual_amount` while retaining per-field immutability after an actual
snapshot value exists. Full-reversal paths lock the corresponding schedule before
the Donation. Payment Entry cancellation also requires one locked installment
whose persisted actual date and amount prove that the complete Donation was
settled. Only then can no submitted allocation plus locked cancelled-allocation
history covering the full amount establish reversal. Cancelling the final leg of
a concurrently full split settlement records the Donation amount and that final
Payment Entry reference. Separate partial settle/cancel attempts never combine
into a full reversal because no full actual snapshot existed.
An exact replay must match the immutable kind/source/reference/amount and any
supplied date, while conflicting provider or accounting evidence is rejected.
Recurring
Donation stores counts plus due expected amount, settled actual amount, and
settlement variance. Reconciliation runs on schedule,
Donation, and Payment Entry changes and daily. The daily job pages schedule
names and commits or rolls back each locked schedule independently; migration
backfills page names without loading the entire table. Composite lookup indexes
cover provider identity, provider transaction replay, and installment matching.
Reconciliation never imports or calls a provider, so it cannot initiate charges.
The post-model backfill uses each schedule's current amount for historical
expected dates because the previous schema retained no amount-effective-date
history. It validates every legacy schedule against the Company's default
currency before writing and aborts with examples on mismatch rather than
relabelling historical amounts. Per-schedule Donation reads are capped.

`Payment Failed` and `Cancelled` are terminal and require category/reason,
optional details, date, and user. Allowed reasons distinguish donor request,
provider final failure/cancellation, end date, provider-verified abandoned
mandate, administration, retired Pause migration, and unknown historical state.
The category/reason Select metadata includes explicit blank defaults and blank
first options; without both, Frappe initializes a new Active schedule with the
first business values. A versioned post-model cleanup removes only that exact
`Donor` / `Donor requested cancellation` contamination from non-terminal rows.
It is idempotent and deliberately leaves every terminal row untouched because
the same values may be legitimate closure evidence there.
The first terminal transition always overwrites submitted date/user values with
the server timestamp and acting session user. Terminal schedules cannot reopen,
repeated terminal actions do not rewrite them,
and their category/reason/details/date/user audit is immutable after closure.
Failure count/date/decline reason remain separate provider evidence. The closure
patch recognizes known retired-Pause
and abandoned-mandate comments; otherwise an old terminal row becomes
Historical rather than being falsely attributed to the donor. The final
expectation on a Payment Failed closure date is Missed; a true Cancelled closure
cancels expectations from that effective date. Natural end-date closure is the
exception: after the final due Donation is generated, its expectation stays
active so it can settle, vary, or become missed. Manual and scheduled local fan-out
close a locked schedule before creating anything when its next date is already
beyond the end date. Provider-verified abandoned mandates reconcile their
expectations immediately after closure.

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
- `demo_data_reset_declarations` registers the app-neutral
  `non_profit.non_profit.demo_data_reset.get_reset_declaration` provider. It
  declares the app-owned fundraising/member records that a reset coordinator may
  marker-scope and delete. Its checker captures only `Recurring Donation
  Installment` rows linked to the captured schedules; cleanup locks each frozen
  row, revalidates its current schedule owner, and deletes those exact names
  through the reconciliation write capability. Cleanup also locks and clears
  `Donor.next_action_task` and `Major Gift.next_action_task` only when both the
  parent and linked Task are in the frozen reset scope; those exact metadata
  edges are declared in `cleanup_managed_links`. Verification queries only the
  frozen names. The provider imports or names no private reset consumer and is
  inert when no consumer resolves the hook.
- `non_profit_referenced_email_providers` (consumed by
  `non_profit.non_profit.mailer.send_referenced_email`) lets a downstream
  delivery app deliver the app's doc-referenced emails
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
- Four daily scheduler jobs expire memberships, process due recurring Donations,
  reconcile fundraising roll-ups, and reconcile recurring expected-versus-actual
  evidence. Recurring reconciliation uses independently committed schedule
  batches so one malformed schedule does not undo earlier repairs.
- Recurring Donation processing creates submitted, unpaid Donation rows for due
  active schedules **that no payment provider owns**. The candidate query
  excludes any schedule carrying `payment_provider`, and the locked worker
  rejects any provider linkage at all, including a pending mandate whose
  subscription id has not been minted. It re-checks ownership because filters can go
  stale between the query and the lock. This exclusion is what makes a
  provider-backed schedule structurally incapable of being charged twice: the
  provider reports every charge it takes, and a second generator running on a
  date would duplicate each one. It obtains the complete current schedule document in one
  locking read, checks that current state is still active and due, and performs
  a locking lookup before reusing or creating the installment for that
  schedule/date. It closes a schedule before creation when the locked
  `next_date` is already after `end_date`, advances `next_date` at most once,
  and commits or rolls back each schedule independently. A
  two-connection regression runs the real worker helper and proves that two due
  workers create one installment. The POST-only manual action also discards its
  caller's stale state and acts on the complete locking read.
- **Provider-backed schedules.** A `Recurring Donation` may record that an
  external payment provider owns it: `payment_provider`,
  `provider_subscription_id`, `provider_reference`, `provider_account` and
  `provider_next_payment`. The naming is deliberately provider-agnostic and
  `provider_account` is a Data field, not a Link — this app is public and must
  stay installable without any payment integration. It never talks to a
  provider itself: `change_amount` and `cancel_schedule` delegate through
  `non_profit_recurring_donation_providers`, and an unclaimed action throws
  rather than silently succeeding, because a no-op would leave the donor
  charged the old amount while the record claims otherwise. Both actions lock
  and authorize the current row; an incomplete provider binding fails closed.
  Cancellation reconciles the local schedule before dispatch, so invalid local
  evidence cannot be followed by an external cancellation.
  Once any provider state exists, ordinary saves cannot rewrite Company,
  status, amount, currency, frequency, or linkage. Those fields and all
  provider lifecycle fields are excluded from copies.
- An incomplete provider-owned `Pending Mandate` cannot use ordinary
  cancellation because a hosted checkout may still become a live mandate.
  `retire_abandoned_pending_mandate` delegates provider verification through the
  same hook and changes the row to Cancelled only after a provider returns
  explicit `safe_to_retire: true` evidence. The action is POST-only, checks the
  current locked row's write permission, stores the provider evidence on the
  timeline, immediately reconciles installment expectations, and otherwise fails closed.
- `provider_account` is pinned when the subscription is adopted and never
  re-resolved. A subscription lives inside one provider account and cannot be
  moved between them, so re-resolving from configuration would address
  whichever account is configured today rather than the one holding the
  donor's mandate.
- Installments from a provider are recorded by `record_provider_installment`,
  which first locks and reloads the current provider-managed schedule. They are
  keyed for idempotency on the **provider's transaction id** rather than the
  date. Provider webhooks retry for days, so a replay reuses existing evidence
  even when the Donation was later cancelled; it never posts replacement
  accounting for the same transaction. A genuinely different charge inside one
  period still records. New paid installments call Donation's authoritative
  `on_payment_authorized` state machine for Payment Entry rollback, thank-you
  dispatch, and donor/Major Gift roll-ups. A charge without a transaction id is
  refused. The Donation's Donor and Company must match the schedule. A trusted
  provider may pass the authenticated amount/payment date and decorate only
  installed value-bearing Donation Custom Fields; standard identity, schedule,
  payment, amount, date, and doctype fields cannot be overridden. The payment
  date becomes both the Donation date and generated Payment Entry
  posting/reference date.
- `apply_provider_status` maps the provider's five lifecycle states onto
  Active / Payment Retrying / Payment Failed / Ending / Cancelled. Payment
  Retrying and Payment Failed stay distinct so staff do not chase donors the
  provider is about to charge successfully, and **Ending still collects** —
  the donor gave notice, and the remaining charges follow. `next_date` becomes
  a mirror of the provider's `valid_until` rather than a driver. Ending cannot
  regress to an earlier state; Payment Failed and Cancelled are terminal, so
  delayed provider events cannot reopen a stopped instruction.
- Provider actions run inside the caller's request transaction but mutate an
  external system before local commit can be proven. Every provider
  implementation must therefore write an immediate non-secret
  `local_commit_pending` recovery journal entry after provider success and pair
  it through `after_commit` / `after_rollback`. Amount updates and cancellation
  must be idempotent so an operator can safely retry the exact action after a
  rollback-confirmed or unpaired-pending entry.
- `Payment Entry` is extended through `doc_events` hooks, not
  `override_doctype_class`: the override resolves to the last installed app
  (hrms wins on this bench), while doc_events fire for every Payment Entry
  regardless of which controller class is active.

## Roles And Desk Access

`Non Profit Manager` and `Non Profit Member` are Desk roles in this bench. Install/migrate setup keeps them enabled with Desk Access and repairs existing users with either role that were left as Website Users. This prevents SSO-created NPO operators from having non_profit DocType permissions but failing Frappe's standard list helpers such as saved `List Filter` loading.

Non-profit setup also disables `auto_opt_in` on ERPNext's known loyalty test
fixtures (`Test Single Loyalty` and `Test Multiple Loyalty`) when they exist.
Those fixtures are created by ERPNext tests and match every Customer, which
otherwise makes normal downstream Customer saves show "Multiple Loyalty Programs
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

`/donate` and `/donate_confirm` are opt-in per site. `get_context` on both
pages starts with `non_profit.www.donate.require_public_donate_pages()`, which
raises `frappe.DoesNotExistError`, which Frappe's website exception wrapper
turns into a real HTTP 404 response, unless `site_config.json` sets
`enable_non_profit_public_donate_pages`. The gate runs before the POST branch,
so a hidden page cannot create Donors or Donations either. The default is off
because these pages are an unstyled EUR fallback and many sites already embed a
branded donation surface;
leaving them reachable duplicates the donation funnel. Flipping the flag needs
`bench clear-website-cache`, since Frappe caches 404 responses per URL.

Public donation pages that delegate to `non_profit.www.donate._handle_submission`
must pass server-side validation for donor name, email syntax, an amount within
the shared public bounds (CHF 5–100'000), accepted consent, and allowed frequency
(`one_off`, `Monthly`; Quarterly and Yearly are staff-only). The amount check rejects non-finite input explicitly: `float()`
accepts `inf`, `-inf`, `nan`, and overflowing literals such as `1e400`, and
`nan` compares False against every bound, so a positivity test alone cannot keep
those values out. `Donation.validate` repeats the same invariant at controller
level so no write path — Desk, import, portal, or bank reconciliation — can
persist a non-finite or non-positive amount. Company is resolved server-side; a
selected or listed Donation Campaign must be active and backed by an enabled
leaf Cost Center belonging to that Company. That campaign/Company gate lives
once in `non_profit.non_profit.campaign_gate.campaign_matches_company()` so
downstream guest surfaces can reuse the same security boundary; ownership is
derived from the campaign's Cost Center, never from the campaign name or
historical Donations. Before any Donor/Customer lookup or creation, the
normalized email acquires the same hashed `Contact Email` identity lock used by
other public and guided identity flows through transaction completion. The
handler then calls
`resolve_donor_customer_identity(..., ambiguous_email_policy="reject")`; it
never selects the first Donor by email. Candidate discovery includes the
individual Donor's canonical `Donor.contact -> Contact.email_id` path as well as
Member/Customer and legacy compatibility paths. Multiple Donors or Customers
return the same neutral guest failure before any identity master or Donation is
created or changed. One Donor plus one same-email Customer is also rejected
unless `Donor.customer` already links them, or the Customer is explicitly
classified as `Person` and shares the Donor's canonical Contact through
`npo_contact`, `customer_primary_contact`, or a Contact Dynamic Link. A Company
Customer's primary contact never proves that the person and company are one
identity. Ambiguity diagnostics use the
`non_profit` application logger with a SHA-256 email fingerprint and candidate
counts, never Error Log: Frappe's Error Log automatically captures request form
metadata that includes the submitted email. Missing Donor Type setup fails
closed only if a new Donor is needed; the guest request never provisions
configuration. Reusing one existing Donor
preserves its name; a different submitted name is an audit Comment only, never
an unauthenticated rename. Browser `required` attributes are
UX only. The handler is rate-limited. Every guest submission must include a
valid GoodVantage CAPTCHA response. Missing Good Connector or missing/unreadable
CAPTCHA configuration fails closed; the app can still be installed without Good
Connector, but public donation submission is unavailable until CAPTCHA support
is installed and configured. The submit control starts disabled and follows the
shared loader's `data-load-state`; server verification remains authoritative.
Because the website handler redisplays `ValidationError` as a normal response,
it performs a full database rollback first. Partial identity, Comment, Donation,
or provider writes and transaction callbacks therefore cannot be committed by a
late public-form validation failure.

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

## Tribute Gifts

Donation stores tribute designation and fulfillment without introducing a
second donor/recipient master. `tribute_type` is `In Honour` or `In Memory` and
requires `tribute_honouree`. A notification request can carry a recipient name,
staff-selected Contact/Address, email, postal-address snapshot, and personal
message. `non_profit.non_profit.tribute.public_tribute_values()` is the guest
boundary: it validates bounded snapshots and never creates, links, renames, or
updates Contact/Address records.

Fulfillment begins as `Pending` only when notification was explicitly requested;
otherwise it is `Not Requested`. No Donation insert, submit, payment callback,
or reconciliation sends a tribute notification. Staff explicitly use the
Donation action to mark a submitted paid gift `Fulfilled` or `Unable`; the latter
requires an internal note. The action requires Donation write permission and
read permission on a linked recipient Contact or Address. Terminal fulfillment
writes date/user/note audit and cannot be supplied by insert/import, direct
submitted-document PUT/save, edited, or switched to another outcome. The guard
runs explicitly in `before_update_after_submit`. The service response contains only the Donation and
status, not recipient details.

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
both Donor and Customer. New Customers require the configured Selling Settings
Customer Group and Territory. Both names must exist and resolve to non-group leaf
rows; blank, nonexistent, or group defaults raise a setup error, with no fallback
to another database row. The `All Customer Groups` root is never assigned. Every
Donor-linked Address is propagated to the Customer, while an existing Customer
primary Address is preserved. When that pointer is blank, only a unique enabled primary Address or
the sole enabled Address is selected. Disabled or unresolved multiple Addresses
never become primary, leaving downstream correspondence to report the ambiguity
instead of hiding it behind an arbitrary pointer. A one-time migrate patch preserves existing
`Donor.email` values by creating/linking Customers before the Donor email field
is removed from the model. The patch runs after DocType model sync so fresh
installs have the newer `Donor.customer` column before it queries donor rows;
`backfill_donor_customers(limit=None)` remains available for explicit repair
runs.

`non_profit.non_profit.donor_identity.resolve_donor_customer_identity()` is the
policy-capable orchestration service for public/presentation callers. Non Profit
owns email normalization, Member-aware Customer lookup, Donor/Customer linking,
canonical Donor Contact-email lookup, and Contact/Address continuity; callers
provide only presentation values, existing-Donor handling, insertion strategy,
and ambiguity policy. Public consumers use safe rejection: when more than one
Donor or Customer resolves to an email, or when a sole Donor and sole Customer
have no existing Donor-Customer link or explicitly Person-classified shared
canonical Contact proving one identity, staff must resolve the records instead
of a guest request choosing or linking them arbitrarily.
The generic `/donate` page and the `Donation` Website User fallback explicitly
pass `ambiguous_email_policy="reject"`; the deprecated gateway compatibility
lookup uses `get_unambiguous_donor_by_email()`. None may select the first Donor
when Donor/Customer evidence is ambiguous. A missing Donor Type is a setup error
rather than a reason to create configuration from public input. The `/donate`
existing-Donor callback may record a submitted name mismatch but does not rename
the master.
The normalized-email Redis lock is held until commit or rollback. Under MariaDB
repeatable-read, candidate discovery runs inside
`identity_lock.current_identity_read()`. While the identity lock is owned it
temporarily disables MariaDB's `innodb_snapshot_isolation` record-change check;
it does not replace the transaction's existing repeatable-read view. The mode
covers only candidate discovery, locking comparison, and the selected-Donor
load, then is restored before caller handlers or identity writes execute. Safety
comes from comparing those snapshot candidates with deterministic current
locking reads and aborting on any difference. Any selected Donor is loaded with
`for_update=True` so unchanged candidate names cannot return stale master fields.
Its snapshot and current `customer` links are also compared before current-read
mode ends. Link drift retries the complete transaction before a normal
repeatable-read Customer existence check can replace a newly committed link.
If the candidate sets drift, `IdentityCandidateDriftError` is both
a `QueryDeadlockError` and `ValidationError`: workers retain their whole-
transaction retry signal, while public handlers can roll back and redisplay one
neutral message without a form-retaining 500 Error Log. Member and Donor
declare indexes in DocType metadata. The `before_install` and `before_migrate`
hooks create the standard `Customer.email_id` Property Setter when absent. A
compatible operator- or foreign-owned setter remains untouched; a conflicting
disable stops setup with an actionable error rather than being taken over. An
unassigned setter is never treated as proof of ownership: compatible behavior
is preserved, while a conflicting disable stops setup without mutation. Only a
new setter or one already assigned to module `Non Profit` is app-owned.
On a fresh install, completed setup registers an after-commit callback because
the app-only sync does not revisit ERPNext's Customer DocType. Migrate registers
the same callback only after every setup step succeeds. It verifies all three
target tables, uses table-specific index names where a backend did not create an
equivalent single-column index, and therefore avoids duplicate and
PostgreSQL/SQLite schema-wide name collisions. Table and column inspection, DDL,
and the final commit all run through a dedicated database object with empty
callback managers, so they cannot re-enter, recurse through, or reorder the
shared install/migrate transaction. No index DDL or commit runs inside the
install/migrate hooks themselves.
`Contact.email_id` and `Donor.contact` are already indexed by their owning
schemas.
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

The guided endpoint is an authenticated Desk workflow, not a wrapper around a
downstream guest endpoint. Before writing, it requires create/read/write permission
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
finite Redis TTL still recovers from worker/process failure. The
`identity-lock:v1:*` keys are exempted from `frappe.clear_cache()` through
Frappe's `persistent_cache_keys` hook: the locks are correctness state that
lives in the cache namespace only because `frappe.cache.lock()` puts them
there, and an unrelated flush (a scheduler tick, a doctype save, a migrate)
would otherwise delete a lease a live transaction still holds and abort it at
the before-commit reacquire. The exemption is registered here as well as in
compatible twins because non_profit installs standalone. Lock keys contain a
hash of the normalized identity type/value rather than PII. Version 16.19.1
uses the neutral shared protocol
`identity-lock:v1:{sha256(normalized_type + "\n" + normalized_value)}` rather
than an app-branded prefix. Compatible co-installed identity engines therefore
derive the same key and mutually exclude one another; a future format change
must bump the protocol version in a coordinated release. Public person-email
paths use semantic type `Contact Email`, not a product role such as
`Individual`, so Non Profit donation/member intake contends with Connector's
production Contact resolver. Both twins use the same neutral request-local
registry for reentrant nested calls. Because Frappe clears rollback callbacks
before `before_commit`, the registry rearms rollback cleanup before lease
validation; callback-first commit/rollback release, an after-commit acquisition
guard, and request/job terminal cleanup cover callback and SQL commit failures.
If current-read cleanup cannot restore MariaDB snapshot isolation, it closes the
session before propagating the restore error. A secondary session-close failure
is logged without replacing that primary error, matching the compatible twin.

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

`Donation.thank_you_sent` is a standard field on Donation for **Verdankungen**. `Donation.send_thank_you()` queues the configured Email Template, stores `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` when available, and marks this field once the email is queued. Downstream presentation apps read this field for pending thank-you queues. A Verdankung is not a Bescheinigung: an immediate thank-you never creates or touches a **Donation Tax Receipt**. A dedicated `Donation Acknowledgement` (Verdankung) document is planned as Phase 5 of `LETTER_DISPATCH_CONVERGENCE_PLAN_2026-07-31.md`; do not re-model it as a second Bescheinigung.

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
payment part.

That layout only holds if the format actually owns the whole sheet. Frappe passes
wkhtmltopdf its page margins through one channel — the four longhand properties
`margin-top` / `margin-right` / `margin-bottom` / `margin-left` on a
`.print-format` rule inside the format's HTML — and the `margin` shorthand is not
parsed. `@page { margin: 0 }` alone is aspirational: any edge left undeclared
falls back to 15mm, which pushes the 210mm-wide payment part off the paper and
clips the payment reference a payer types into e-banking. The format therefore
declares all four longhands as zero, and a test asserts them through Frappe's own
`get_print_format_styles` parser rather than a private copy of the rule, so the
check cannot drift from the real PDF path. Every shipped revision of the body is
added to `DONATION_SLIP_CH_MANAGED_HASHES`, which is how migrate tells its own
previous output from an operator edit it must preserve.

`swiss_qrbill.py` is a neutral dispatch seam, not a renderer. It calls
`non_profit_qr_bill_svg_providers` in hook order and uses the first non-empty
SVG. With no provider, printing continues without a payment part. Ordinary
provider errors are logged and dispatch continues; database deadlocks and lock
timeouts propagate unchanged and without logging so the complete print/email
transaction can retry.

The downstream provider owns creditor/debtor resolution, IBAN and address
validation, QRR behavior, and recipient language. A real QR-IBAN receives the
Donation's stored shared QRR; an ordinary IBAN never receives a QRR. Keeping the
public app renderer-free avoids a second regulated payment implementation that
can drift from the shared engine.

`Non Profit Settings.creditor_iban` is an optional provider-facing override.
The shared deployment provider normalizes and validates that value first; when
it is blank, it resolves the Donation Company's default Bank Account. Creditor
identity and structured address still come from the Company master data. If
neither account source plus the Company Address is valid, the provider returns
no payment part.

## Membership Integration Compatibility

Downstream membership consumers use:

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
presentation app's own fields.
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
Membership Type; downstream apps use this for parent-owned business
memberships. The guided raw-data Desk input mode is additive on the
same endpoint and does not change the original arguments or response keys.

If any of these contracts change, adjust every downstream consumer and run its
membership-related tests.

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
flows where billing is triggered by a later process after customer data has
been collected. The shared
`non_profit.non_profit.membership_subscription.ensure_membership_subscription`
helper returns without creating anything unless the Membership Type is marked as
a subscription. For subscription-enabled types, it creates or reuses an ERPNext
**Subscription Plan**, creates an open-ended ERPNext **Subscription** for the
linked Customer using **Non Profit Settings -> Company** as the accounting
company unless an explicit company argument is passed, writes
`Membership.subscription`, and clears
`Membership.to_date` when requested. Presentation apps should call this helper
instead of creating Subscription rows locally.

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

**Major Gift** is one concrete cultivation ask per record. `stage` drives the
reduced pipeline (Qualification → Cultivation → Solicitation, plus terminal
**Won** / **Lost**) and is the Kanban field. It stores one `ask_amount`; the
former expected/probability/weighted forecast fields and duplicate outcome field
were removed. `inquiry_channel` records the first-contact/inquiry source as
Email, Letter, Phone, Website Form, or Other. The standard **Mark Won** and
**Mark Lost** actions open a required reason dialog and store the answer in
`won_reason` or `lost_reason` as part of the same workflow transition. The
typed, POST-only `apply_outcome_workflow` endpoint checks write permission,
accepts only Mark Won/Mark Lost, and delegates to Frappe's standard workflow
engine with a request-local reason so the workflow reload and save remain
authoritative. Server validation protects interactive transitions and explicit
reason edits, while historical terminal records are not made invalid solely
because they predate these fields. Entering a terminal stage stamps `closed_on`,
and `closed_amount` is the sum of submitted, paid Donations linked through
`Donation.major_gift`.
Major Gift is not submittable.

Relationship history uses native Frappe comments: general notes belong on the
Donor timeline and ask-specific notes on the Major Gift timeline. There is no
separate Donor Interaction model or interaction-date roll-up.

### Pipeline Workflow

A **Major Gift Pipeline** Workflow (built by `major_gifts.ensure_major_gift_workflow`
on `after_migrate`) drives the `stage` field. It is code-owned:

- **States** are Qualification, Cultivation, Solicitation, Won, and Lost, all at `doc_status = 0`
  (Major Gift is not submittable).
- **Transitions** are Cultivate, Solicit, and Mark Won in sequence; **Mark Lost**
  is available from every open stage, and **Reopen** moves Lost back to
  Qualification. Won is terminal; a later ask gets a new Major Gift.
- **Permission-preserving role.** Workflow role `All` exposes transitions to
  every user who already has Major Gift write permission without importing
  downstream role names into this public app. `allow_self_approval` remains
  enabled.

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

A "next action" on a Donor or Major Gift is a real ERPNext **Task**, not free
text. Logic lives in `non_profit/non_profit/next_actions.py`. Each Task links to
its Donor through `Task.donor`; gift-specific Tasks also carry
`Task.major_gift`. Creating a Task from a Major Gift fills both links, so the
same work is visible from the ask and the long-term donor relationship.

The Donor and Major Gift `next_action` (Small Text), `next_action_date` (Date), and
`next_action_task` (Link → Task) fields reflect the earliest *open* linked Task
(`status not in Completed/Cancelled/Template`, ordered by `exp_end_date`). They
are recomputed by `refresh_next_action`, which runs from `set_next_action` and
from the `Task` `on_update`/`on_trash` doc_event (`on_task_change`) — so completing
or rescheduling a Task updates the rollup. On Major Gift only, **Follow-up Date**
(`next_action_date`) is editable when no Task is linked and is shown in the list
view. Once an open Task controls the fields, the date is read-only; completing
or deleting the last open Task clears it, and staff may then enter a new manual
date. No hidden former manual date is restored. Donor remains Task-derived.
Keeping the `next_action*` fieldnames means existing reports keep working.

Operators use **Actions → Set Next Action** on either form (POST-only whitelisted
`non_profit.non_profit.next_actions.set_next_action`, gated by parent write
permission): it prompts for the action, due date, and assignee (defaulting to the
relationship manager), then creates, shares, assigns (standard Frappe
assignment), and links the Task. Scoped shares let the creator and assignee work
with that Task without granting downstream roles access to every ERPNext Task.
The internal share write bypasses the creator's Task share right only after the
endpoint has verified write permission on the Donor or Major Gift. Task
validation derives `Task.donor` from `Task.major_gift`, and the
`sync_major_gift_task_donors` patch backfills existing gift Tasks and refreshes
both old and new Donor roll-ups. Direct Task saves and deletions require write
permission on every current or previous linked fundraising parent. A Major
Gift's Donor becomes immutable once a Donation or Task is linked.
The form **Connections** tab lists linked Tasks. The
`convert_next_actions_to_tasks` patch migrates pre-existing free-text values.

The 16.11.0 pre-model patch `simplify_major_gifts` maps Identification to
Qualification and Stewardship to Solicitation, deletes every Task linked through
the retired `Task.donor_interaction` field, removes that Custom Field, deletes
all Donor Interaction records/metadata/table, and removes stale workspace links.

Donor gains `relationship_manager`, `donor_level`
(Prospect/Grassroots/Annual/Mid-Level/Major), `capacity_rating`, a read-only
`is_major_donor` flag, and hook-maintained giving roll-ups
(`total_lifetime_amount`, `gift_count`, `first_gift_date`, `last_gift_date`,
`last_gift_amount`, `largest_gift_amount`). Donor also carries the derived
next-action fields shared with Major Gift.

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
bench --site development16.localhost run-tests --module non_profit.non_profit.test_major_gift_migration
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.donation.test_donation --test TestDonationPaymentEntryInvariants.test_two_connections_allow_exactly_one_full_allocation
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.recurring_donation.test_recurring_donation
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.npo_recipient_selection.test_npo_recipient_selection
bench --site development16.localhost run-tests --module non_profit.non_profit.test_tax_receipts
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

## Release 16.20.0 (2026-08-16)

- Adds the two neutral channel-architecture seams (REQ-NP-CHAN-01…03): the
  hook-driven recipient-selection channel registry
  (`non_profit_recipient_selection_channels`) replacing the hardcoded
  newsletter/direct_mail pair in availability validation, channel gating and
  launch-source `available_channels`; and `channel_router.send_transactional`
  with `non_profit_transactional_channels`, reviving `Donor.receipt_delivery`
  (now offering `Messenger`) as a *reader* for 1:1 transactional flows —
  donation thank-you and tax confirmation. Registered channels are additive:
  with no registered channel, or any default preference, every existing path
  keeps its exact behavior. This app registers no channel and imports none.

## Release 16.19.2 (2026-08-14)

- Exempts `identity-lock:v1:*` keys from `frappe.clear_cache()` through
  Frappe's `persistent_cache_keys` hook. The locks land in the Redis cache
  namespace only because `frappe.cache.lock()` puts them there, so any
  unrelated flush — a scheduler tick, a doctype save, a migrate — deleted a
  lease a live transaction still held, and the holder's before-commit
  reacquire aborted the transaction with "Identity serialization expired".
  Registered in this app as well as in good_connector because non_profit owns
  its own identity-lock copy and installs without it.

## Release 16.19.1 (2026-08-12)

- Moves the ephemeral identity-lock key to the versioned neutral
  `identity-lock:v1:` protocol so compatible co-installed identity engines
  serialize the same normalized person or organization bench-wide. Public
  person-email paths use semantic type `Contact Email`, and the lifecycle now
  rearms rollback cleanup after Frappe's callback reset with terminal cleanup
  for failed commit/rollback chains.

## Release 16.19.0 (2026-08-11)

- Promotes the canonical Customer and Contact display-name rules to tested
  public helpers used by Member and Donor identity surfaces.

## Wave A duplication fixes (2026-08-11, 16.18.3)

- Donation thank-you and Membership acknowledgement emails select the template body via `non_profit.utils.email_template_body` (`response_html` if `use_html` else `response`, D16): an HTML-stored template no longer renders empty and a stale plain-text body no longer wins. Pinned as a public twin by good_connector's correspondence parity suite.
- `utils.split_person_name` is the one public split convention (first token = given name); good_npo delegates its fallback to it (D1).
