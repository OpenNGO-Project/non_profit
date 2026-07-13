# Non Profit - Documentation

## Purpose

`non_profit` is this bench's shared NPO domain app. It is a hard fork of Frappe's Non Profit app with Swiss fundraising additions and membership changes used by `ilanga_app`, `miki_app`, and Goodvantage apps.

## Important Consumers

| App | Dependency |
|---|---|
| `ilanga_app` | Dashboard, print assets, and public Ilanga pages over non_profit doctypes. |
| `miki_app` | Membership/Customer substrate for kibesuisse declarations. |
| `good_npo` | Generic Goodvantage NPO presentation layer. |
| `good_demo` | Demo signup/reset layer that seeds non_profit demo records. |

Breaking changes are allowed while Miki is not production, but `miki_app` must be updated in the same change whenever shared membership behavior changes.

## Key DocTypes

- **Member** and **Membership** for membership identity, periods, invoicing, and B2B/B2C flows.
- **Donor**, **Donation**, **Donation Campaign**, **Recurring Donation**, and **Donation Receipt** for fundraising. `Donor.customer` is the canonical ERPNext Customer relation for donor identity; Donation still links to Donor.
  Donation carries analysis dimensions `cost_center` (fetched from the campaign's cost center when empty) and `project` (both ERPNext doctypes) for downstream fundraising analytics (e.g. the `good_analytics` app).
- **Sponsor**, **Sponsor Tier**, **Volunteer**, and **Grant Application** for broader NPO operations.
- **Non Profit Settings** for company, donor type, billing, invoicing, payment account, and email defaults.

## Hooks

- `after_install = non_profit.setup.setup_non_profit`
- `after_migrate = non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures` refreshes non_profit custom fields and fundraising fixtures.
- `before_tests = non_profit.non_profit.utils.before_tests` refreshes the same fundraising fixtures after the CI/test setup wizard creates a Company.
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
- `Payment Entry` is extended through `override_doctype_class`.

## Roles And Desk Access

`Non Profit Manager` and `Non Profit Member` are Desk roles in this bench. Install/migrate setup keeps them enabled with Desk Access and repairs existing users with either role that were left as Website Users. This prevents SSO-created NPO operators from having non_profit DocType permissions but failing Frappe's standard list helpers such as saved `List Filter` loading.

Non-profit setup also disables `auto_opt_in` on ERPNext's known loyalty test
fixtures (`Test Single Loyalty` and `Test Multiple Loyalty`) when they exist.
Those fixtures are created by ERPNext tests and match every Customer, which
otherwise makes normal NPO/Miki Customer saves show "Multiple Loyalty Programs
found" messages. Real Loyalty Program records are left untouched.

## Whitelisted API Contracts

Mutation endpoints must check permissions and let Frappe manage the request
transaction. `DonationReceipt.generate_yearly_receipts` is restricted to
`Non Profit Manager` or `System Manager` and creates draft receipts for
submitted, paid Donations without an existing receipt link or active draft
receipt row.
`get_donations_for_selected_year` is an authenticated, permission-aware helper
used by the Donation Receipt form action to populate a draft receipt with all
submitted paid Donations for the selected Donor and Fiscal Year. Donation
Receipts can be saved before donation rows are added, but submit requires at
least one Donation and validates that every row is submitted, paid, in the
receipt period, belongs to the receipt Donor, and is not already linked to
another active receipt. The period comparison normalizes Frappe Date values and
Desk JSON string dates before validation. Donation Receipt country defaults to
`Switzerland` in DocType metadata, the yearly-generation dialog, and the backend
fallback when no country argument is supplied.
`get_campaign_donation_chart(campaign, year=None)` on the Donation Campaign
controller requires read permission on the Campaign and returns twelve monthly
buckets for submitted paid donations on that campaign in the selected year.
Segments are donation-level so the Desk form chart can open the underlying
Donation directly.
`DonationReceipt` email sending, chapter staff edits, and grant review
invitations require write permission on the target document. A logged-in portal
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
must pass server-side validation for donor name, email syntax, positive amount,
accepted consent, allowed frequency (`one_off`, `Monthly`, `Quarterly`,
`Yearly`), and an active Donation Campaign when a campaign is selected. Browser
`required` attributes are UX only. The handler is rate-limited. If
`good_connector` is installed and a GoodVantage CAPTCHA site key is configured,
guest submissions must include a valid CAPTCHA response; sites without
Good Connector remain standalone and skip the optional CAPTCHA gate.

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
Donor.customer`. Donor no longer stores its own email address; donor email is
read from `Donor.customer -> Customer.email_id` and copied onto Donation /
Recurring Donation / Donation Receipt rows as an operational snapshot.
`Donor.preferred_language` and `Donation Receipt.language` are Link fields to
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

Desk creation helpers for Member, Donor, and Sponsor accept Contact-only,
Customer-only, or Contact+Customer selections. The Member list uses Frappe's
native `listview_settings.primary_action` hook to open its combined Member and
Membership creation dialog directly; each Add action creates a fresh dialog,
and cancelling it leaves the user on the list instead of an unsaved Member form.
Contact-only Donors keep a Contact
Dynamic Link and no Customer until a Customer is explicitly selected through a
creation/import/repair flow.
Sponsor creation reuses the same Donor identity helper before creating/reusing
the Sponsor. Contact Dynamic Links are appended through the parent Contact
document, not inserted as standalone child rows. These helpers explicitly require
create permission for the target record plus write permission on selected
Contacts/Customers before they append links or update Customer/Donor identity
fields. Conflicting Contact+Customer selections are rejected instead of silently
moving a Contact to another Donor/Member. Volunteer creation intentionally
accepts Contact only and links the Contact to Volunteer without creating or
linking a Customer.

`Donation.thank_you_sent` is a standard field on Donation for **Verdankungen**. `Donation.send_thank_you()` queues the configured Email Template, stores `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` when available, and marks this field once the email is queued. Presentation apps such as `ilanga_app` and `good_npo` read this field for pending thank-you queues. `Donation.receipt` remains reserved for **Donation Receipt** / **Spendenbescheinigung** tax certificates, so an immediate thank-you must not populate it.

`Donation.on_payment_authorized()` sets `paid = 1` before optional accounting
side effects. Automated Payment Entry failures are logged with the Donation
name and do not prevent thank-you dispatch. This keeps hosted-checkout payment
callbacks from being rolled back by single-company account settings on
multi-demo sites.
The `Payment Entry` override also syncs Donation references: submitting a
Payment Entry with a `Donation` reference marks that Donation paid when the
submitted allocation total covers the Donation amount, and cancellation
recalculates the flag from the remaining submitted Payment Entries.
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

### Donation QR Slips

`Donation.before_print()` generates the Swiss QR-bill SVG in Python and stores
it on `doc.qr_bill_svg` for the seeded `Donation Slip CH` Print Format. The
Print Format only renders that prepared value; it must not call QR generators
from Jinja. The slip body renders first, and the QR-bill is placed at the bottom
of a separate final page so normal document footer behavior does not overlap the
payment part. Missing creditor configuration is reported before checking the
optional `qrbill` Python package, so setup errors remain visible even on CI
images that do not install the QR-bill dependency.

Note: this bench intentionally runs two Swiss QR-bill engines. non_profit's
`swiss_qrbill.py` (qrbill package, creditor from Non Profit Settings) renders
Donation slips, while `good_connector.qr_bill` (chqr package, creditor from
the Company bank account, with QRR/SCOR reference support) renders invoice
QR pages for miki_app / good_event / good_npo. They cannot share code —
non_profit is standalone and must not import good_connector. When changing
payment-relevant QR behavior, check both engines.

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
dates belong only to `Membership`; Member is the identity record and can be
linked to a Customer for B2B flows. Contact-only person memberships are linked
through Contact Dynamic Link rows; Member does not store a Contact field.

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
derive the name from the Contact and link the Contact through Dynamic Link rows.
The Member Desk form does not write membership validity dates back onto Member;
if a legacy `membership_expiry_date` field exists, the client refreshes it from
the linked Membership without marking the form dirty.
The legacy manual `Membership.generate_invoice()` path requires the legacy
`Membership.invoice` link field and is not exposed when that field is absent.
Current app-specific membership billing should link Sales Invoices through the
presentation app's own fields, for example `Sales Invoice.good_npo_membership`.
The Contact/Customer dialog and helper accept Contact, Customer, or both, create
or reuse the Member first, link the Contact to both Member and Customer when both
are selected, then create or reuse an open-ended Membership for the selected
Membership Type;
presentation apps such as `miki_app` use this for parent-owned business
memberships.

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
`major_gifts.recompute_all_donor_giving`) backfill existing donors.

Non Profit Settings → **Major Gifts** adds `major_donor_threshold` (auto-flag).
`stale_interaction_days` and `lapsed_major_months` are reserved — defined but
not yet wired to any behavior.

## Test Commands

```bash
cd frappe-bench
bench --site development16.localhost run-tests --app non_profit
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.major_gift.test_major_gift
bench --site development16.localhost run-tests --module non_profit.non_profit.doctype.donor_interaction.test_donor_interaction
bench --site development16.localhost run-tests --module miki_app.tests.test_end_to_end
```

`non_profit.non_profit.utils.before_tests` also normalizes local ERPNext bootstrap
preconditions before the suite runs: it uses a short in-process test host URL,
renames fixed ERPNext test Customers when local Customer naming is set to naming
series, and pre-creates ERPNext test Addresses with `pincode` for Swiss benches
where that field is mandatory.
