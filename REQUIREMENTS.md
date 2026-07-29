# REQUIREMENTS.md — Non Profit

Requirements for `non_profit`. This file is the requirement-level source of
truth: requirements, `DOCUMENTATION.md`, `HOW_TO.md`, and the code must
match. Update this file whenever requirements change; keep requirement IDs
stable (never reuse a retired ID — mark it "Retired:" with the reason).

Status: retrofitted on 2026-07-17 from current code, existing docs, and
archived agent sessions (opencode/Claude/Codex). Describes what the app is
required to do today, not a historical design spec.

## 1. Purpose and Scope

`non_profit` is the Goodvantage bench's shared fundraising and membership
substrate: a hard fork of Frappe's Non Profit app for Frappe v16 with Swiss
fundraising additions (yearly donation receipts, Swiss QR-bill donation
slips, donor thank-yous) and reworked membership semantics (B2C + B2B,
Households, subscription billing). It is consumed by `miki_app`
(membership/Customer substrate for kibesuisse declarations), `good_npo`
(presentation layer), `good_demo` (demo seeding), and `ilanga_app`, and its
donation data feeds `good_analytics`; `good_direct_mail` consumes its canonical
correspondence and Household Donor services.

Explicitly out of scope / dependencies:

- Payment-provider integrations (checkout, webhooks, callback verification)
  live in gateway apps such as `payrexx_integration`, never here.
- Client-specific UI, seeding, branding, and presentation flows belong to
  `good_npo` / `ilanga_app` / client apps; this app stays generic.
- ERPNext is a required app (`hooks.py required_apps`); its `Task`, Customer,
  Payment Entry, Subscription, and Bank Transaction doctypes are always
  present. `good_connector` integration is optional (defensive imports) and
  the app must remain installable without it.
- The app does not provide legally approved Swiss tax-certificate wording or
  a company-derived currency contract (see §4).

## 2. Functional Requirements

### 2.1 Membership and Member Management

- REQ-NP-MEM-01: Contact is the canonical person identity; Member is a membership role projected from that Contact and may also link an operating Customer. One Contact can back at most one role of each type. Canonical role Contacts are assigned only through conflict-checked identity helpers and cannot be added, cleared, or retargeted by an ordinary save of an existing role; a new role carrying a Contact requires Contact write permission unless created by a trusted permission-bypassing flow. Membership Type, Status, and validity dates live only on `Membership` — Member stores no `membership_type`. Member names are operator-editable; when `member_name` is blank and a Customer is linked, the controller fills it from `Customer.customer_name` plus `Customer.name_additional` when that field exists. [Trace: `non_profit/non_profit/doctype/member/`, `non_profit/non_profit/utils.py`, `non_profit/non_profit/doctype/membership/`; Tests: `doctype/member/test_member.py`, `doctype/membership/test_membership.py`]
- REQ-NP-MEM-02: Both B2C (`Membership.member`) and B2B (`Member.customer` → Customer) membership links are supported; `Membership.company` is removed and business/organisation context resolves through `Membership.member -> Member.customer -> Customer`. [Trace: `non_profit/non_profit/membership_sync.py` (`get_customer_for_membership`, `list_customer_memberships`), `patches/remove_membership_company`; Tests: `doctype/membership/test_membership_sync.py`]
- REQ-NP-MEM-03: Overlapping active Memberships for the same member are rejected on validate; callers may downgrade the hard stop to a warning by setting `doc.flags.warn_on_membership_overlap = True` before validation. [Trace: `non_profit/non_profit/membership_sync.py::validate_no_overlap`, `hooks.py doc_events`; Tests: `doctype/membership/test_membership_sync.py`]
- REQ-NP-MEM-04: Memberships can be open-ended: the default billing-cycle `to_date` fill is bypassed when callers set `membership.flags.keep_to_date_open = True` before insert; the Desk label of `to_date` is "Membership Until". [Trace: `non_profit/non_profit/doctype/membership/membership.py`; Tests: `doctype/membership/test_membership.py`]
- REQ-NP-MEM-05: Recurring billing is opt-in per Membership Type (`is_subscription`); `ensure_membership_subscription` creates/reuses an ERPNext Subscription Plan and an open-ended ERPNext Subscription only for subscription-enabled types, writes `Membership.subscription`, and leaves `to_date` open when requested. [Trace: `non_profit/non_profit/membership_subscription.py`; Tests: `doctype/membership/test_membership.py`]
- REQ-NP-MEM-06: A daily scheduler job expires memberships whose validity has passed. [Trace: `hooks.py scheduler_events.daily` → `membership.set_expired_status`; Tests: `doctype/membership/test_membership.py`]
- REQ-NP-MEM-07: The combined Member+Membership creation endpoint retains its technical Contact-only, Customer-only, or Contact+Customer input contract, creates/reuses the Member first, stores `Member.contact` and `subject_type` for a person, links the Contact to both Member and Customer when both are selected, then creates/reuses an open-ended Membership for the chosen Membership Type. [Trace: `doctype/member/member.py::create_member_and_membership` (whitelisted POST); Tests: `doctype/member/test_member.py`]
- REQ-NP-MEM-08: When "Send Membership Acknowledgement" is enabled in Non Profit Settings, a saved Membership exposes a Send Acknowledgement action that emails the configured Email Template and Membership Print Format. [Trace: `doctype/membership/membership.py::send_acknowlement`; Tests: `doctype/membership/test_membership.py`]
- REQ-NP-MEM-09: `NPO Organization` is the canonical organization identity anchor, separate from ERPNext Customer/Supplier operating parties. Stage 1 ships the serial-named master plus hidden preparatory identity fields on Contact, Customer, Supplier, Member, Donor, and Volunteer; organization-role synchronization and merge tooling are deferred. [Trace: `doctype/npo_organization/`, role DocType JSON, `non_profit/setup.py`; Tests: `non_profit/test_party_model_schema.py`]
- REQ-NP-MEM-10: When Good Connector is installed, the Member list primary action must open a guided **Create Member** Desk dialog for an Individual or Organization; without it, the original technical Contact/Customer selector remains available. Individual creation requires first/last name, email, street/house number, postal code, city, country, Membership Type, and From Date (phone optional); Organization creation requires the organization name and accepts an optional complete human contact person plus optional complete address. Country defaults from the site. Optional Existing Contact and Existing Address selectors must load and lock their identity fields; the server treats selected records as authoritative after record permission/classification checks and adds only missing links, while blank selectors retain exact automatic reuse. The existing authenticated `create_member_and_membership` POST endpoint accepts this additive guided input shape while retaining REQ-NP-MEM-07's technical wire contract. It must pre-authorize create/read/write access on Contact, Address, Customer, Member, and Membership, require read access on selected Membership Type/Country records, use Good Connector deterministic Contact/Address identity matching, serialize person-email and organization identities through transaction completion, reuse only unambiguous canonical links (never an unrelated same-email Customer), reject Generic Endpoint/contradictory/ambiguous identities, and create a Current open-ended Membership or reuse an existing active Current period without rewriting its configured dates. It must not commit or send correspondence. Individuals store `Member.contact`; Organization Members use a Company/Partnership Customer and keep human Contacts as non-canonical Dynamic Links. [Trace: `non_profit/non_profit/member_identity.py`, `doctype/member/member.py::create_member_and_membership`, `doctype/member/member_list.js`; Tests: `doctype/member/test_member.py`]

### 2.2 Households

- REQ-NP-HH-01: Household groups people who share a postal address into one solicitation unit via dated `Household Person` child rows (`contact`, optional `relationship`, `from_date`, `to_date`, `is_primary`). A row without `to_date` is current; normal move-out/divorce handling sets `to_date` so history remains visible. Addresses and Contacts attach through standard Dynamic Links rendered like on Member/Donor; `Customer.household` (Link → Household) and `Contact.title` remain available. [Trace: `non_profit/non_profit/doctype/household/`, `non_profit/setup.py::get_custom_fields`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-02: Household validation requires `from_date`, rejects `to_date < from_date`, duplicate current rows for the same Contact, more than one current primary per Household, a second current Household for a Contact, and Contacts explicitly classified as non-people. A Contact already used by a canonical person role or Household Person row cannot later be reclassified as `Generic Endpoint`. [Trace: `doctype/household/household.py`, `non_profit/utils.py`, `hooks.py`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-03: Concurrent Household row saves are serialized by locking affected canonical Contact rows in deterministic order before querying conflicting `Household Person` rows; ordinary derived-field reads during Member/Donor validation do not lock Household rows. Deletion retains Contact permission checks but does not take a Contact lock after Frappe has already locked the Household parent, avoiding an inverted lock order. [Trace: `doctype/household/household.py`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-04: Contact Household state is projected to every Member/Donor role carrying that Contact through `frappe.db.set_value` (never by saving the role document, avoiding recursive validation). Saved and persisted prior rows are reconciled so correction, retargeting, and deletion cannot leave stale role state; attaching an existing role to a Contact immediately refreshes the same projection. The read-only role fields are also restored by their controllers on save. [Trace: `doctype/household/household.py`, `doctype/member/member.py`, `doctype/donor/donor.py`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-05: The read-only `Membership.is_household_membership` flag is set in `Membership.validate` and refreshed on all Memberships of affected Members whenever household links change. [Trace: `doctype/household/household.py`, `doctype/membership/membership.py`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-06: `add_person_to_household(household, contact, from_date, to_date=None, is_primary=False, relationship=None, *, ignore_permissions=False)` is the canonical service for presentation apps to append dated person history; it requires write permission on both Household and Contact unless an explicitly trusted caller passes `ignore_permissions=True`. [Trace: `doctype/household/household.py::add_person_to_household`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-07: Household access is restricted to `Non Profit Manager`, matching Donor access, because a Household may expose multiple NPO roles; normal saves and deletion require write permission on affected Contacts. [Trace: `doctype/household/household.json`, `doctype/household/household.py`; Tests: `doctype/household/test_household.py`]
- REQ-NP-HH-08: Postal language preference is stored on the canonical communication subject: `Contact.preferred_language` is a setup-owned editable Link to Language, while `Household.preferred_language` is a normal Household Link field. Neither field receives an invented default. [Trace: `non_profit/setup.py::get_custom_fields`, `doctype/household/household.json`; Tests: `non_profit/test_correspondence_profile.py`]

### 2.3 Fundraising — Donors, Donations, Campaigns

- REQ-NP-FUN-01: `Donor.customer` is the canonical ERPNext Customer relation for operating/accounting identity; Donor stores no own email. For an individual Donor, email resolves from the canonical `Donor.contact` first; organization or legacy roles fall back to `Donor.customer -> Customer.email_id`, then a linked Contact. The result is copied onto Donation / Recurring Donation / Donation Receipt rows as an operational snapshot. `Donor.preferred_language` and `Donation Receipt.language` are Link fields to Frappe's `Language` DocType storing codes such as `de` or `en`. [Trace: `non_profit/non_profit/doctype/donor/donor.py`, `doctype/donor/donor.json`, `doctype/donation_receipt/donation_receipt.json`, `patches/backfill_donor_customers_from_email`; Tests: `doctype/donor/test_donor.py`, `doctype/donation_receipt/test_donation_receipt.py`]
- REQ-NP-FUN-02: `get_or_create_customer_for_donor()` reuses a Customer from a same-email Member first, then a same-email Customer, and otherwise creates a new Customer, linking Contact and Address rows to both Donor and Customer and persisting the individual Donor's canonical Contact projection. A Customer-only company Donor remains an Organization role backed by its Company Customer; linked contact people/mailboxes do not become its canonical person Contact. [Trace: `doctype/donor/donor.py`; Tests: `doctype/donor/test_donor.py`]
- REQ-NP-FUN-03: `resolve_donor_customer_identity()` is the policy-capable orchestration service for public/presentation callers: non_profit owns email normalization, Member-aware Customer lookup, Donor/Customer linking, and Contact/Address continuity, while callers supply presentation values, existing-Donor handling, insertion strategy, and ambiguity policy (`ambiguous_email_policy="reject"` sends duplicate identities to staff review). [Trace: `non_profit/non_profit/donor_identity.py`; Tests: `doctype/donor/test_donor.py`]
- REQ-NP-FUN-04: Desk creation helpers for Donor and Sponsor accept Contact-only, Customer-only, or Contact+Customer selections and require create permission for the target record plus write permission on selected Contacts/Customers; Contact-only individual Donors store `Donor.contact` plus the Contact Dynamic Link and no Customer until one is explicitly selected, conflicting Contact+Customer selections are rejected instead of silently moving a Contact, and Sponsor creation reuses the same Donor identity helper and fetches the Sponsor name from the backing Donor. [Trace: `doctype/donor/donor.py::create_donor_from_identity`, `doctype/sponsor/sponsor.py::create_sponsor_from_identity` (whitelisted POST); Tests: `doctype/donor/test_donor.py`, `doctype/sponsor/test_sponsor.py`]
- REQ-NP-FUN-05: Donation carries the analysis dimensions `cost_center` (fetched from the campaign's cost center when empty) and `project` for downstream fundraising analytics. [Trace: `doctype/donation/donation.py`, `doctype/donation/donation.json`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-FUN-06: The Donation Campaign Desk form shows a year-selectable chart of twelve monthly buckets for submitted, paid donations with donation-level segments that open the underlying Donation; `get_campaign_donation_chart` requires read permission on the Campaign, and campaign totals (`refresh_totals`) count submitted, paid Donations — the same semantics used by donor roll-ups. [Trace: `doctype/donation_campaign/donation_campaign.py::get_campaign_donation_chart` (whitelisted), `donation_campaign.js`; Tests: `doctype/donation_campaign/test_donation_campaign.py`]
- REQ-NP-FUN-07: `Donation.send_thank_you()` queues the configured thank-you Email Template, stores `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by`, and marks the standard `thank_you_sent` field; `Donation.receipt` remains reserved for Donation Receipt tax certificates and must not be populated by an immediate thank-you. [Trace: `doctype/donation/donation.py`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-FUN-08: The non-whitelisted correspondence-profile service resolves bounded batches (maximum 500 canonical/source references and 5,000 supplied related identities) without mutating master data. Existing `(doctype, name)`, `{doctype, name}`, and `{reference_doctype, reference_name}` sources remain valid. A canonical mapping supplies `canonical_subject_type` (`Contact`/`Person`, `Customer`/`Organization`, or `Household`), `canonical_subject`, and optional `contacts`, `members`, `donors`, and `customers`; those related rows contribute language and Address candidates without replacing the declared canonical Contact, Customer, or Household. String values are not accepted as reference sequences, and bounds are checked before unbounded iterable materialization. The service returns deterministic current Household people, structured addressee/name components, language plus exact field provenance, and deduplicated active Address candidates plus link provenance. Generic Endpoint Contacts cannot satisfy a person subject. Missing and ambiguous identity, Household, language, addressee, and Address states use stable explicit issue codes. Address Dynamic Links are queried by exact target pairs rather than independent DocType/name cross-products. Address resolution accepts one explicit direct pointer, one uniquely primary candidate, or one sole candidate; zero emits `MISSING_ADDRESS`, while unresolved multiplicity emits `AMBIGUOUS_ADDRESS` rather than selecting the first row. [Trace: `non_profit/non_profit/correspondence.py`; Tests: `non_profit/test_correspondence_profile.py`]
- REQ-NP-FUN-09: `get_or_create_donor_for_household(household, donor_type=None, *, ignore_permissions=False)` locks only the Household parent row before lookup, rejects ambiguity across canonical Household-subject Donors and legacy blank-`subject_type` rows carrying the same `subject_household`, reuses the sole matching canonical or legacy Donor, or creates one with the Household name and canonical `subject_household`. It does not create a Household Customer or another identity master. Normal calls require Household write and Donor read/create permission. [Trace: `doctype/donor/donor.py::get_or_create_donor_for_household`; Tests: `doctype/donor/test_donor.py`]

### 2.4 Donation Receipts

- REQ-NP-RCP-01: `generate_yearly_receipts` is restricted to `Non Profit Manager` or `System Manager` and creates draft receipts for submitted, paid Donations in the selected fiscal year that are not already linked to a submitted receipt or another active draft receipt; the default receipt country is `Switzerland` in DocType metadata, the yearly-generation dialog, and the backend fallback. [Trace: `doctype/donation_receipt/donation_receipt.py::generate_yearly_receipts` (whitelisted); Tests: `doctype/donation_receipt/test_donation_receipt.py`]
- REQ-NP-RCP-02: `get_donations_for_selected_year` is an authenticated, permission-aware helper that populates a draft receipt with all submitted, paid Donations for the selected Donor and Fiscal Year. [Trace: `doctype/donation_receipt/donation_receipt.py` (whitelisted); Tests: `doctype/donation_receipt/test_donation_receipt.py`]
- REQ-NP-RCP-03: A Donation Receipt may be saved empty, but submit locks selected Donation rows in deterministic name order, refreshes receipt ownership under those locks, then requires at least one row and validates that every row is submitted, paid, inside the receipt period (normalizing Frappe Date values and Desk JSON string dates), belongs to the receipt Donor, and is not already linked to another active receipt. [Trace: `doctype/donation_receipt/donation_receipt.py` validate/on_submit; Tests: `doctype/donation_receipt/test_donation_receipt.py`]
- REQ-NP-RCP-04: `send_to_donor()` requires write permission on the receipt and currently attaches the seeded `Donation Receipt DE` print format; it must not be used for another jurisdiction until the send contract is deliberately extended (see §4). [Trace: `doctype/donation_receipt/donation_receipt.py::send_to_donor`; Tests: `doctype/donation_receipt/test_donation_receipt.py`]

### 2.5 Payments and Accounting Integration

- REQ-NP-PAY-01: `Donation.on_payment_authorized()` is the authoritative payment state machine: it ignores statuses other than `Authorized`/`Completed`, temporarily sets `paid = 1`, creates the configured Payment Entry when automatic creation is enabled, resets `paid`, logs, and raises on accounting failure, and only then calls the narrow `_dispatch_payment_thank_you()` policy seam. [Trace: `doctype/donation/donation.py`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-PAY-02: The `Payment Entry` doc_events hooks sync Donation references and expose only the Donation amount not already allocated by submitted Payment Entries; a fully allocated Donation cannot create another Payment Entry, and final submission locks all referenced Donation rows in name order and rejects a cumulative allocation above the Donation amount. The integration is hook-based rather than an `override_doctype_class` controller override (last-installed-app resolution made the override inert once hrms registered its own Payment Entry class), and Donation carries maintained `grand_total` / `advance_paid` mirrors so ERPNext's generic reference-details fallback computes the correct outstanding amount under any active Payment Entry controller. [Trace: `non_profit/non_profit/custom_doctype/payment_entry.py`, `hooks.py doc_events`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-PAY-03: Donation Payment Entries must use the Donation company and its expected Donor receivable account (the configured Donation Debit Account when it belongs to that company, otherwise ERPNext's company-specific Donor party account); global Non Profit Settings accounts are applied only when the configured Account belongs to the Donation company, and cancellation recalculates the Donation paid flag from the remaining submitted Payment Entries. [Trace: `non_profit/non_profit/custom_doctype/payment_entry.py`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-PAY-04: `Donation.reconciled`, `reconciled_on`, and `reconciled_payment_entry` are read-only mirrors of submitted Donation Payment Entries whose `clearance_date` was set by ERPNext Bank Clearance or Bank Transaction reconciliation; the `Bank Transaction` override only syncs these mirrors after ERPNext updates the linked Payment Entry and does not change ERPNext's bank reconciliation rules. [Trace: `non_profit/non_profit/custom_doctype/bank_transaction.py`, `custom_doctype/payment_entry.py`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-PAY-05: A read-only bench helper reports submitted Donation references whose cumulative allocations exceed the Donation amount, whose Payment Entry company differs from the Donation company, or whose Donor-side account differs from the currently expected account; it is not whitelisted and never updates data — corrections go through normal ERPNext cancellation/reversal workflows. [Trace: `custom_doctype/payment_entry.py::audit_donation_payment_entry_invariants`; Tests: none]
- REQ-NP-PAY-06: `Donation.before_print()` generates the Swiss QR-bill SVG in Python and stores it on `doc.qr_bill_svg` for the seeded `Donation Slip CH` Print Format, which only renders the prepared value (no QR generators in Jinja); missing creditor configuration is reported before checking the optional `qrbill` package. [Trace: `non_profit/non_profit/swiss_qrbill.py`, `doctype/donation/donation.py`; Tests: `doctype/donation/test_swiss_qrbill.py`]
- REQ-NP-PAY-07: The development-only `Donation.mock_pay` endpoint is guest-whitelisted but POST-only and inert unless both `developer_mode` and the `enable_non_profit_mock_payments` site-config flag are set. [Trace: `doctype/donation/donation.py::mock_pay`; Tests: `doctype/donation/test_donation.py`]
- REQ-NP-PAY-08: When Good Connector is installed on the site, every new submitted Donation receives a collision-checked, Donation-namespaced 27-digit `gc_qr_reference`, while any valid stored legacy QRR remains immutable; migrate idempotently backfills only missing references. A QR-IBAN Donation slip emits that stored QRR, and non_profit registers a side-effect-free EBICS candidate provider plus trusted unsaved Donation Payment Entry builder. The provider uses a deterministic ordered read without provider-side locking and returns every submitted same-company Donation sharing the QRR before amount eligibility so duplicate identities always require review. A sole exact identity remains an ineligible candidate when currency or outstanding policy blocks automation, preventing another provider from silently winning; it is automatic only when the Bank Transaction, Company, receiving bank Account, and expected Donor receivable Account use the Company currency and the remaining outstanding covers the credit. Good Connector owns target locking, aggregate ambiguity handling, voucher submission, and Bank Transaction linking. [Trace: `non_profit/non_profit/bank_integration.py`, `non_profit/non_profit/swiss_qrbill.py`, `hooks.py`; Tests: `doctype/donation/test_bank_integration.py`, `test_swiss_qrbill.py`]

### 2.6 Recurring Donations

- REQ-NP-REC-01: A daily scheduler job locks each due active Recurring Donation and compares its locked `next_date` with the date initially observed by that invocation, reuses an existing non-cancelled installment for the same schedule/date instead of duplicating it, creates a submitted unpaid Donation when needed, advances `next_date` at most once per invocation, and cancels schedules that pass `end_date`, committing or rolling back each schedule independently so one failing schedule does not undo the batch; the "Create Next Donation Now" action uses serialized installment creation and also advances the schedule, and `Paused` stops generation without ending the instruction. [Trace: `doctype/recurring_donation/recurring_donation.py` (`process_recurring_donations`, whitelisted `create_next_donation`), `hooks.py scheduler_events`; Tests: `doctype/recurring_donation/test_recurring_donation.py`]

### 2.7 Major Gifts and Donor Interactions

- REQ-NP-MG-01: Major Gift tracks one cultivation ask per record; `stage` drives the pipeline (Identification → Qualification → Cultivation → Solicitation → Stewardship, plus terminal Won/Lost), `ask_amount`/`expected_amount`/`probability` produce a read-only `weighted_amount`, terminal stages stamp `outcome` and `closed_on` and force probability (Won = 100, Lost = 0), and `closed_amount` is the sum of submitted, paid Donations linked through `Donation.major_gift`. [Trace: `doctype/major_gift/`, `non_profit/non_profit/major_gifts.py`; Tests: `doctype/major_gift/test_major_gift.py`]
- REQ-NP-MG-02: A code-owned "Major Gift Pipeline" Workflow (all states at doc_status 0, forward transitions, Mark Won, Mark Lost from any open stage, Reopen, single gating role with `allow_self_approval`) is built on `after_migrate` and hash-stamped so it is rebuilt only when the shipped definition changes and a migrate never reverts operator edits. When the optional Workflow Visualizer field is installed, setup enables its process rail independently without rebuilding operator-edited Workflow rows; installing Workflow Visualizer after Non Profit applies the opt-in immediately through Frappe's `after_app_install` hook. [Trace: `major_gifts.py::ensure_major_gift_workflow`, `non_profit.setup.after_app_install`, `WORKFLOW_VERSION_KEY`; Tests: `non_profit/test_fundraising_setup.py`, `doctype/major_gift/test_major_gift.py`]
- REQ-NP-MG-03: `advance_major_gift_to_stage(doc, target_stage)` computes the shortest forward path through the transition graph (excluding Reopen) from the gift's current stage and saves one legal single-step transition at a time. [Trace: `major_gifts.py::advance_major_gift_to_stage`; Tests: `doctype/major_gift/test_major_gift.py`]
- REQ-NP-MG-04: Donor Interaction logs a touchpoint (Call / Meeting / Email / Letter / Event / Proposal / Note / Other) linked to a Donor and an optional Major Gift; a linked Major Gift (on either Donation or Donor Interaction) must belong to the same Donor, and save/trash refreshes `Donor.last_interaction_date` and `Major Gift.last_interaction_date` to the latest interaction. [Trace: `doctype/donor_interaction/`; Tests: `doctype/donor_interaction/test_donor_interaction.py`]
- REQ-NP-MG-05: A "next action" on a Major Gift or Donor Interaction is a real ERPNext Task back-linked through the `Task.major_gift` / `Task.donor_interaction` custom fields; the parents' `next_action`, `next_action_date`, and `next_action_task` fields are read-only and derived from the earliest open linked Task, recomputed on parent save and on Task `on_update`/`on_trash`; the whitelisted `set_next_action` endpoint is gated by parent write permission and creates, assigns (standard Frappe assignment), and links the Task, defaulting the assignee to the gift's `relationship_manager` / interaction's `staff`. [Trace: `non_profit/non_profit/next_actions.py`, `setup.py::get_custom_fields`, `hooks.py doc_events.Task`; Tests: `doctype/major_gift/test_major_gift.py`, `doctype/donor_interaction/test_donor_interaction.py`]
- REQ-NP-MG-06: Donor giving roll-ups (`total_lifetime_amount`, `gift_count`, `first_gift_date`, `last_gift_date`, `last_gift_amount`, `largest_gift_amount`) recompute from a Donation's `on_submit`/`on_cancel`/`on_trash` and after `on_payment_authorized`, counting submitted, paid Donations; `is_major_donor` is set when `donor_level == "Major"` or lifetime giving reaches `Non Profit Settings.major_donor_threshold`, and roll-ups recompute inline when a Donation's `paid` flag flips through the Payment Entry flow. [Trace: `major_gifts.py::on_donation_change`, `custom_doctype/payment_entry.py`; Tests: `doctype/major_gift/test_major_gift.py`, `doctype/donor/test_donor.py`]
- REQ-NP-MG-07: A daily `reconcile_fundraising_rollups` scheduler job rebuilds every Donor roll-up and Major Gift closed amount using grouped Donation aggregates and a set-based latest-gift lookup (`date desc, modified desc`), writing only changed rows through chunked `frappe.db.bulk_update`, so out-of-band changes and `major_donor_threshold` edits retro-apply. [Trace: `major_gifts.py::reconcile_fundraising_rollups`, `hooks.py scheduler_events`; Tests: `doctype/major_gift/test_major_gift.py`]

### 2.8 Community — Chapters, Volunteers, Grants

- REQ-NP-COM-01: A logged-in portal user may join a published Chapter only as themselves and may leave only their own active Chapter row; editing another user's Chapter row requires Chapter write permission. [Trace: `doctype/chapter/chapter.py` (whitelisted POST `join`/`leave`); Tests: `doctype/chapter/test_chapter.py`]
- REQ-NP-COM-02: Member-supplied `website_url` values are restricted to `http(s)://` URLs server-side, and the public chapter page escapes member-supplied `website_url` / `introduction` values when rendering. [Trace: `doctype/chapter/chapter.py`, chapter templates; Tests: `doctype/chapter/test_chapter.py`]
- REQ-NP-COM-03: Grant review invitations require write permission on the Grant Application and an Assessment Manager before the status is moved to `In Progress`; logged-in applicants use the `/my-grant` page and the `grant_application` web form. Published grant pages explicitly escape applicant-supplied values and never render the applicant email. [Trace: `doctype/grant_application/grant_application.py`, `doctype/grant_application/templates/grant_application.html`, `non_profit/non_profit/web_form/grant_application/`; Tests: `doctype/grant_application/test_grant_application.py`]
- REQ-NP-COM-04: Volunteer creation intentionally accepts a person Contact only, requires a Volunteer Type and an email, stores `Volunteer.contact`, and links the Contact to the Volunteer without creating or linking a Customer; a Contact explicitly classified as a generic endpoint is rejected. [Trace: `doctype/volunteer/volunteer.py::create_volunteer_from_contact` (whitelisted POST); Tests: `doctype/volunteer/test_volunteer.py`]

### 2.9 Public Web Surfaces

- REQ-NP-WEB-01: The public `/donate` page validates server-side donor name, email syntax, positive amount, accepted consent, allowed frequency (`one_off`, `Monthly`, `Quarterly`, `Yearly`), and an active Donation Campaign when one is selected. The handler is rate-limited (20/hour), and every guest submission must include a valid GoodVantage CAPTCHA response; missing Good Connector or missing/unreadable CAPTCHA configuration fails closed. [Trace: `non_profit/www/donate.py::_handle_submission`; Tests: `non_profit/test_donate.py`]
- REQ-NP-WEB-02: The `/donate_confirm` page is key-gated: every Donation gets a random `confirmation_key` on insert, the donate flow redirects via `donation_confirm_query()` with `?donation=<name>&key=<key>`, and the page refuses to disclose donor name or amount without a matching key because Donation names are a sequential series; logged-in users with Donation read permission can open the page without a key, pages that build their own confirm redirect must use `donation_confirm_query()`, and Donations created before the key field existed are not guest-viewable. [Trace: `non_profit/www/donate_confirm.py`, `non_profit/www/donate.py::donation_confirm_query`, `doctype/donation/donation.py::before_insert`; Tests: `non_profit/test_donate.py`]

### 2.10 Desk, Workspace, Reporting, and Help

- REQ-NP-DSK-01: The app ships the "Non Profit" Workspace and Workspace Sidebar as source fixtures (sidebar with `app: "non_profit"`, `module: "Non Profit"`, `standard: 1`) covering Good Help, fundraising, Major Gifts, membership, people (Contact, Address, Household, Customer, and Supplier), community, settings, and the Expiring Memberships report. Frappe permission-filters the upstream People links; Non Profit roles do not grant broad access to those ERPNext masters. [Trace: `non_profit/non_profit/workspace/non_profit/`, `non_profit/workspace_sidebar/non_profit.json`; Tests: none]
- REQ-NP-DSK-02: The "Expiring Memberships" report derives one row per Member from the latest non-cancelled Membership (`MAX(to_date)`) and filters that date against the selected month/fiscal year, without referencing the removed `Membership.paid` field. [Trace: `non_profit/non_profit/report/expiring_memberships/`; Tests: none]
- REQ-NP-DSK-03: Serial-named doctypes are searchable by human title: `title_field`, `in_standard_filter`, and doctype-level `search_fields` are set per the bench convention (Donor, Member, Donor Interaction, Major Gift, Grant Application, Volunteer, …). [Trace: doctype JSON metadata; repo `AGENTS.md` "List-View Search"; Tests: none]
- REQ-NP-DSK-04: Markdown under `non_profit/fixtures/help/non_profit/` is synced into editable Wiki Documents by Good Help's installed-app scan when `good_help` is installed, and the sidebar links to `/app/good-help?app=non_profit`. [Trace: `non_profit/fixtures/help/non_profit/`; Tests: none]
- REQ-NP-DSK-05: Desk form and list operations use Frappe's Actions menu APIs (`frm.page.add_action_item`, `listview.page.add_action_item`/`add_actions_menu_item`) instead of visible inner-toolbar buttons so views remain usable on mobile. [Trace: doctype JS files, repo `AGENTS.md` rules; Tests: none]

### 2.11 Setup, Install, and Migration

- REQ-NP-SETUP-01: Install/migrate setup (`setup_non_profit` on `after_install`, `non_profit.setup.after_migrate` on `after_migrate`) creates/updates the standard-master custom fields (`Customer.household`, `Contact.title`, `Contact.preferred_language`, hidden NPO identity fields on Contact/Customer/Supplier, and Task links), assigns them to the Non Profit module for ordered uninstall cleanup, repairs a declared Custom Field whose physical column is missing, and refreshes Non Profit Settings defaults and fundraising fixtures idempotently. The optional `after_app_install` integration reacts only to a later Workflow Visualizer installation and does not make that app a required dependency. Missing `Donation Receipt DE` and `Donation Slip CH` Print Formats are inserted; an existing body is upgraded only when it matches a known shipped-content hash, while operator-edited bodies are preserved. `Donation Thank You DE` remains create-only. Only when Good Connector is installed on the current site does setup ask the shared setup to create Donation QRR and EBICS fields. [Trace: `non_profit/setup.py`, `non_profit/non_profit/fundraising_setup.py`, `hooks.py`; Tests: `non_profit/non_profit/test_party_model_schema.py`, `non_profit/non_profit/test_correspondence_profile.py`, `test_fundraising_setup.py`, `doctype/non_profit_settings/test_non_profit_settings.py`, `doctype/donation/test_bank_integration.py`]
- REQ-NP-SETUP-02: Setup keeps the `Non Profit Manager` and `Non Profit Member` roles enabled with Desk Access and repairs existing users holding either role from `Website User` to `System User`, so SSO-created operators do not fail standard list helpers such as saved `List Filter` loading. [Trace: `non_profit/setup.py::ensure_non_profit_desk_roles`; Tests: `doctype/non_profit_settings/test_non_profit_settings.py`]
- REQ-NP-SETUP-03: Migrate patches remove India-specific PAN/80G data (legacy Donor/Member PAN custom fields, 80G certificate DocTypes and tables), remove the unused Certification module (DocTypes, tables, web forms) through a separately identified corrective patch for sites that already logged the original cleanup, remove `Membership.company`, backfill donor Customers from legacy emails (post-model-sync), backfill major-gift donor roll-ups, and convert free-text next actions into Tasks. The pre-model Household patch resolves every legacy Member/Donor child row to exactly one Contact, backfills canonical role links, coalesces only exact same-person current duplicates, renames the child DocType/table, recovers a populated old table left by prior orphan cleanup without dropping that backup, and aborts before mutation on detached rows, invalid dates/primaries, or missing, ambiguous, conflicting, and non-person identity data; a post-model patch classifies migrated Contacts and refreshes role projections. [Trace: `non_profit/patches.txt`, `non_profit/patches/`; Tests: `non_profit/non_profit/test_party_model_schema.py` and app suite]
- REQ-NP-SETUP-04: Setup disables `auto_opt_in` on ERPNext's known loyalty test fixtures (`Test Single Loyalty`, `Test Multiple Loyalty`) when they exist, leaving real Loyalty Program records untouched. [Trace: `non_profit/non_profit/erpnext_loyalty.py` via setup; Tests: `doctype/non_profit_settings/test_non_profit_settings.py`]
- REQ-NP-SETUP-05: `before_tests` normalizes local ERPNext bootstrap preconditions (short in-process test host URL, renaming fixed ERPNext test Customers under naming-series Customer naming, pre-creating ERPNext test Addresses with `pincode` on Swiss benches) and refreshes fundraising fixtures after the CI/test setup wizard creates a Company. [Trace: `non_profit/non_profit/utils.py::before_tests`, `hooks.py`; Tests: itself test infrastructure]

## 3. Non-Functional Requirements

### 3.1 Security and Permissions

- REQ-NP-SEC-01: Whitelisted mutation endpoints enforce permissions server-side (explicit `check_permission("write")` / `frappe.only_for(...)`), because `run_doc_method` only enforces read permission; email sending, chapter staff edits, grant review invitations, yearly receipt generation, next-action creation, and identity creation helpers are all gated. [Trace: `doctype/donation/donation.py`, `doctype/membership/membership.py`, `doctype/recurring_donation/recurring_donation.py`, `doctype/donation_receipt/donation_receipt.py`, `non_profit/next_actions.py`, `doctype/chapter/chapter.py`, `doctype/grant_application/grant_application.py`; Tests: per-doctype test modules]
- REQ-NP-SEC-02: Every `@frappe.whitelist()` function carries type hints (enforced by `frappe/semgrep-rules` `frappe-missing-type-hints-in-whitelisted-function`). [Trace: all whitelisted endpoints; repo `SEMGREP_OVERRIDES.md`; Tests: none — CI lint]
- REQ-NP-SEC-03: The guest-reachable surface is minimal and gated: the mock payment endpoint requires `developer_mode` plus an explicit site-config flag (documented `nosemgrep` override), the donate handler is rate-limited and requires CAPTCHA with fail-closed configuration, the confirm page is key-gated against the sequential Donation naming series, and member-supplied chapter content is URL-scheme-restricted and escaped on render. [Trace: `doctype/donation/donation.py::mock_pay`, `www/donate.py`, `www/donate_confirm.py`, `doctype/chapter/chapter.py`, `SEMGREP_OVERRIDES.md`; Tests: `non_profit/test_donate.py`, `doctype/donation/test_donation.py`, `doctype/chapter/test_chapter.py`]
- REQ-NP-SEC-04: Donor, Member, and Company records must not retain PAN/tax-id details: migrate removes the legacy fields and India-specific 80G DocTypes physically, and donation gateway note import filters PAN/tax-id keys before creating Donor comments. [Trace: `patches/remove_member_pan_details`, `patches/remove_donor_pan_details`, `patches/remove_tax_exemption_80g`, gateway note import in legacy payments; Tests: none]
- REQ-NP-SEC-05: Identity creation helpers reject conflicting Contact+Customer selections instead of silently moving a Contact to another Donor/Member, reject Contacts explicitly classified as non-people from person roles/Households, and send ambiguous guest-facing donor or guided Desk Member identities to staff review rather than merging arbitrarily. The guided Member flow performs all DocType permission preflights before its first write and checks resolved records before mutation. [Trace: `doctype/donor/donor.py`, `doctype/member/member.py`, `non_profit/member_identity.py`, `doctype/volunteer/volunteer.py`, `doctype/household/household.py`, `non_profit/donor_identity.py`; Tests: role and Household test modules]

### 3.2 Performance

- REQ-NP-PERF-01: Donation Receipt validation, submit, selected-year lookup, and yearly generation share one bulk context loader for Donation fields and active receipt ownership (resolved by joining receipt items to non-cancelled receipts), group loaded rows in Python instead of database-specific `GroupConcat`, and write receipt links set-based; large yearly runs load eligible rows in batches without per-row reads. [Trace: `doctype/donation_receipt/donation_receipt.py`; Tests: `doctype/donation_receipt/test_donation_receipt.py`]
- REQ-NP-PERF-02: All-record fundraising reconciliation uses grouped Donation aggregates plus a set-based latest-gift lookup and sends only changed rows through chunked `frappe.db.bulk_update`; the single-record hook APIs remain the synchronous path for individual Donation changes. [Trace: `major_gifts.py::reconcile_fundraising_rollups`; Tests: `doctype/major_gift/test_major_gift.py`]
- REQ-NP-PERF-03: The recurring-donation batch commits each schedule fan-out independently (documented `nosemgrep` override) so one failing schedule rolls back alone without undoing earlier generated Donations. [Trace: `doctype/recurring_donation/recurring_donation.py`, `SEMGREP_OVERRIDES.md`; Tests: none]

### 3.3 Compatibility and Upgrade Safety

- REQ-NP-COMP-01: Legacy Membership invoice/Payment Entry implementations and Donation gateway-object helpers live in `non_profit/non_profit/legacy_payments.py`; their historical controller/module dotted paths remain thin compatibility facades emitting warnings through the `non_profit.compatibility` logger, and must not be removed earlier than 90 days after warning telemetry is deployed and one complete release cycle reports zero calls. [Trace: `non_profit/non_profit/legacy_payments.py`; Tests: `doctype/donation/test_donation.py`, `doctype/membership/test_membership.py`]
- REQ-NP-COMP-02: The membership substrate contracts consumed by `miki_app` — `membership_sync.get_customer_for_membership`, `membership_sync.list_customer_memberships`, the Member helper functions, `Member.customer`, and `Membership.member` as canonical link — must stay stable; any change to Member/Membership semantics requires updating `miki_app` in the same change and running its membership-related tests. [Trace: `non_profit/non_profit/membership_sync.py`, `doctype/member/member.py`; Tests: `doctype/membership/test_membership_sync.py`, plus `miki_app.tests.test_end_to_end`]
- REQ-NP-COMP-03: `good_connector` integration — CAPTCHA on the donate page and identity matching for legacy Member registration (exact matches reused, ambiguous data creates a fresh Contact, fuzzy matches go to the shared duplicate review queue) — is via optional imports so the fork remains installable without Good Connector. A site without Good Connector may still install the app, but guest donation submission fails closed until CAPTCHA support is installed and configured. The donation submit control stays disabled until the shared CAPTCHA loader reports `loaded`, remains disabled in loading/retrying/error states, and can recover through the loader's manual retry; server verification remains authoritative. [Trace: `non_profit/www/donate.py`, `non_profit/www/donate.html`, `doctype/member/member.py`; Tests: `non_profit/test_donate.py`]
- REQ-NP-COMP-04: The fork tracks Frappe v16 semantics: no `Membership.paid` references anywhere (removed upstream assumption), and raw SQL functions are not used inside `frappe.db.get_value` (query builder instead). [Trace: `report/expiring_memberships/`, `major_gifts.py`; Tests: app test suite]
- REQ-NP-COMP-05: Older public helper dotted paths (`find_donor_by_email()`, `get_or_create_customer_for_donor()`) remain supported alongside the orchestration service. [Trace: `doctype/donor/donor.py`, `non_profit/donor_identity.py`; Tests: `doctype/donor/test_donor.py`]
- REQ-NP-COMP-06: `bench install-app`/`uninstall-app` must not leave the working tree dirty on a dev site: the `before_uninstall` hook clears this app's Workspace Sidebar ownership so developer-mode uninstall does not delete the shipped sidebar JSON, and install/migrate seed functions must not re-save fixture-backed documents without actual changes. [Trace: `non_profit/setup.py::before_uninstall`, `hooks.py`, bench-root `AGENTS.md` install-hygiene rules; Tests: none]

### 3.4 Operations

- REQ-NP-OPS-01: The three daily scheduler jobs (membership expiry, recurring-donation processing, fundraising roll-up reconciliation) are idempotent and safe to re-run. [Trace: `hooks.py scheduler_events.daily`; Tests: per-domain test modules]
- REQ-NP-OPS-02: Operator edits to the Major Gift Pipeline Workflow (roles, extra transitions, `is_active=0`) survive migrate because the definition is hash-stamped and rebuilt only when the shipped states/transitions/role change. [Trace: `major_gifts.py::ensure_major_gift_workflow`; Tests: `doctype/major_gift/test_major_gift.py`]
- REQ-NP-OPS-03: Smoke/test entry points are documented and must stay runnable: `run-tests --app non_profit`, focused Household/Major Gift/Donor Interaction modules, `ensure_fundraising_fixtures` via `bench execute`, and `miki_app.tests.test_end_to_end` after membership changes. [Trace: repo `AGENTS.md` / `HOW_TO.md` / `DOCUMENTATION.md` test sections; Tests: itself]

## 4. Explicit Decisions and Constraints

Intentional behaviors a reader might otherwise mistake for bugs (documented in
`DOCUMENTATION.md` and `HOW_TO.md` unless noted):

- **Receipt jurisdiction contract.** `Donation Receipt DE` is the only
  seeded/send-time receipt print format and contains German tax-law wording
  (`§ 10b EStG`, `§ 5 KStG`). `default_receipt_country = Switzerland` is only
  a data default — it does not translate, validate, or approve the format for
  Switzerland. Deployments must install a legally approved
  jurisdiction-specific format before issuing tax certificates; the app
  deliberately does not invent Swiss legal wording. (`DOCUMENTATION.md`
  "Receipt jurisdiction contract", `HOW_TO.md` "Currency and receipt
  jurisdiction")
- **Currency is a presentation assumption, not a contract.** The base `/donate`
  page, confirmation labels, and the seeded `Donation Thank You DE` template
  display EUR; `Donation Slip CH` displays CHF. Donation has no currency
  field, so production sites must provide one approved currency-aware
  presentation flow.
- **Compatibility facades are a telemetry hold, not forgotten debt.** Legacy
  payment/invoice dotted paths warn through the `non_profit.compatibility`
  logger and stay until ≥ 90 days of telemetry plus one zero-call release
  cycle (audit finding B28; `legacy_payments.py`, `HOW_TO.md`).
- **Two Swiss QR-bill engines on this bench, intentionally.** non_profit's
  `swiss_qrbill.py` (qrbill package, creditor from Non Profit Settings)
  renders Donation slips; `good_connector.qr_bill` (chqr package, creditor
  from Company bank account) renders invoice QR pages. They do not share a
  payment-document implementation: non_profit keeps its donation-slip renderer
  independent, while reusing Good Connector's QRR generation/validation and
  optional EBICS reconciliation services.
- **`Membership.company` was removed on purpose.** It was never the member's
  business relation; resolve organisation context via `Membership.member ->
  Member.customer -> Customer` (`patches/remove_membership_company`).
- **`Donation.receipt` vs `Donation.thank_you_sent`.** Immediate thank-yous
  (Verdankungen) must never populate `Donation.receipt`, which is reserved for
  Donation Receipt tax certificates.
- **The Household child table IS the history.** Leaving a household means
  setting `to_date` on the Contact row rather than deleting it; `Member.household` /
  `Donor.household` are read-only role projections that change through
  Household rows or the canonical `add_person_to_household` service (Household
  audit findings 2026-07; repo `AGENTS.md` "Household Model").
- **The Contact-based Household child has an ordered migration.** The 16.3.0
  pre-model patch converts `Household Member` rows before schema sync and the
  post-model patch finalizes identity classification and projections. It fails
  closed before conversion when a legacy role cannot be mapped unambiguously;
  never bypass that stop by deleting old child rows.
- **Household lock-order convention.** Mutation paths always acquire
  canonical Contact locks in deterministic order before querying conflicting
  Household Person rows; ordinary derived-field reads during role validation
  are deliberately non-locking (Stage 1 party model, 2026-07).
- **Next actions are real Tasks, by design.** The `next_action*` fieldnames
  are kept read-only/derived so the pipeline list and reports keep working off
  them; pre-existing free-text values were migrated to Tasks by patch.
- **Stricter Payment Entry validation is intentional.** Stale drafts and
  alternate accounts are rejected even where historical data violates the
  invariants; the known over-allocated Donation `NPO-DTN-2026-00436` (excess
  246) is flagged for manual review and must not be auto-repaired (audit
  worklist wave 2, `AUDIT_REMEDIATION_WORKLIST_2026-07-14.md`).
- **Mock payments are not a payment path.** The guest `mock_pay` endpoint is
  development-only, POST-only, and gated by two site flags; production payment
  confirmation must come from a real gateway integration.
- **Member dashboard intentionally omits Bank Account.** Bank details belong
  to the linked ERPNext Customer, not to Member.
- **Guided Organization Contacts are correspondence people.** An Organization
  Member is backed by an Organization Customer and has no canonical
  `Member.contact`. An optional named human Contact is linked to the Customer
  and Member through standard Dynamic Links; the foundation/company itself is
  never represented as a Contact. Organization addresses are operational
  address links, not postal-consent metadata.
- **ERPNext loyalty test fixtures are neutralized on purpose.** Setup disables
  `auto_opt_in` only for ERPNext's known test fixtures so NPO Customer saves
  do not show "Multiple Loyalty Programs found"; real Loyalty Programs are
  untouched.
- **Reserved settings fields.** `Non Profit Settings` fields
  `stale_interaction_days` and `lapsed_major_months` are defined but
  intentionally not yet wired to any behavior.

## 5. Sources

- Code: `non_profit/hooks.py`, `non_profit/setup.py`, `non_profit/patches.txt`
  + `non_profit/patches/`, `non_profit/non_profit/` (all 24 active doctype
  directories incl. controllers/JSON, `custom_doctype/`, `donor_identity.py`,
  `membership_sync.py`, `membership_subscription.py`, `major_gifts.py`,
  `next_actions.py`, `correspondence.py`, `legacy_payments.py`, `swiss_qrbill.py`,
  `erpnext_loyalty.py`, `fundraising_setup.py`, `utils.py`,
  `report/expiring_memberships/`, `web_form/grant_application/`),
  `non_profit/www/donate.py`, `non_profit/www/donate_confirm.py`,
  workspace/workspace_sidebar fixtures, `non_profit/fixtures/help/non_profit/`,
  tests tree (25 test modules incl. `non_profit/test_donate.py` and
  `non_profit/test_correspondence_profile.py`).
- Docs: repo `AGENTS.md`, `README.md`, `DOCUMENTATION.md`, `HOW_TO.md`,
  `SEMGREP_OVERRIDES.md`; bench-root `/workspace/development/AGENTS.md`;
  audit files `/workspace/development/CUSTOM_APPS_AUDIT_2026-07-17.md`
  (non_profit status rows: H1, H2, B19, B22–B24 fixed, B28 telemetry hold,
  one P3 bloat note on `before_uninstall` duplication) and
  `/workspace/development/AUDIT_REMEDIATION_WORKLIST_2026-07-14.md`
  (wave 2 accounting invariants, waves 9–10 perf/cleanup).
- Sessions (opencode SQLite, 5 targeted title queries + 5 session drills):
  Household hardening acceptance criteria (`ses_09167fab...`), Wave 10
  B19/B22/B28 donor-identity/legacy-payments cleanup (`ses_09b8f188...`),
  Household lock-order inversion fix (`ses_0913bcec...`), good_npo household
  integration contract (`ses_0915e406...`), two non_profit commit-readiness
  audits (`ses_16240ff6...`, `ses_09174084...`).
- Sessions (Claude jsonl, 6 keyword greps over 204 files, 3 transcripts
  drilled): major-donor process design ask and "moves tracking" decision
  (`25701349...`), bench-wide custom-app audit request (`34ceb6b4...`);
  remaining hits were good_analytics/good_npo sessions name-dropping
  non_profit.
- Sessions (Codex jsonl, 1 grep + 2 transcripts drilled): no direct
  non_profit requirement signals — hits were miki_app/login-branding sessions.
