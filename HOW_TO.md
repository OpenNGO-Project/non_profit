# Non Profit - How To

`non_profit` is the shared fundraising and membership substrate for downstream
site, presentation, analytics, and dispatch apps.

## Install Or Update

```bash
cd frappe-bench
bench --site development16.localhost install-app non_profit
bench --site development16.localhost migrate
```

ERPNext must already be installed.

Workflow Visualizer is optional and may be installed before or after Non Profit.
When it is installed later, Non Profit immediately enables the Major Gift
Pipeline rail through Frappe's app-install hook; no additional migrate is needed
for that opt-in.

NPO desk operators need `Non Profit Manager` or `Non Profit Member` with Desk Access. Setup repairs those roles and existing users during install/migrate. If an SSO-created user gets **Insufficient Permission for List Filter** on a non_profit list, run migrate/setup and have the user log in again.

The shipped **Non Profit** workspace and sidebar expose current fundraising,
Major Gifts, membership, community, settings, report, and Help links. Shared
party masters (**Contact**, **Address**, **Household**, **Customer**, and
**Supplier**) are grouped under **People**. Frappe hides each upstream master
link unless the user already has its normal ERPNext read permission; the Non
Profit roles do not grant broad Contact, Address, Customer, or Supplier access.
Assign the appropriate ERPNext product role only when the operator's duties
require it. The Help link requires `good_help`; Good Help syncs these Markdown
fixtures into editable Wiki Documents.

## Configure Core Settings

Open **Non Profit Settings** and set at least:

- default Company for memberships and donations,
- default Donor Type,
- membership billing cycle,
- invoice and payment accounts when automated invoicing or payment entries are enabled,
- default thank-you Email Template when donation thank-you email should be sent.

Do not configure provider-specific checkout or webhook credentials in
`non_profit`. Payment gateways live in the payments layer, for example
`payrexx_integration`; those apps should verify provider callbacks and then
mark the relevant Donation, Sales Invoice, Membership, or Subscription through
the standard document APIs.

### Exposing the generic donation pages

`/donate` and `/donate_confirm` are **off by default** — both answer 404 and
`/donate` accepts no submission. Most sites should leave them off: they are an
unstyled fallback with EUR labels, and a site that embeds its own branded
donation form or campaign page would otherwise carry a second, off-brand
donation surface.

To serve them on a site that really needs them:

```bash
bench --site <site> set-config enable_non_profit_public_donate_pages 1
bench --site <site> clear-website-cache
```

Clearing the website cache is not optional in either direction — Frappe caches
404 responses per URL, so a freshly enabled page keeps 404-ing (and a freshly
disabled one keeps rendering) until the cache is dropped. Remove the key from
`site_config.json` and clear the cache again to hide the pages.

### Currency and receipt jurisdiction

The generic `/donate` and `/donate_confirm` pages currently display **EUR**, and
the seeded `Donation Thank You DE` email also formats EUR. The separate
`Donation Slip CH` Swiss QR slip displays CHF. Donation has no currency field,
so these labels do not derive from the Donation Company. Production sites must
provide a locally approved, currency-aware presentation flow.

The Bescheinigung is the seeded **Spendenbescheinigung** Print Format for
**Donation Tax Receipt**: German wording, CHF, calendar tax year, itemized
donation table, and the Swiss confirmation sentence. It is address-free by
design — donor address and issuer identity come from the **Letter Head** you
select on the letter campaign or the print view. If your organisation needs a
legally reviewed local variant, edit the format in Desk; migrate will then leave
it alone forever.

You may edit **Spendenbescheinigung**, **Donation Slip CH**, and **Donation Thank
You DE** in Desk. Migrate updates a Print Format only while its HTML still
matches known app-shipped content; any operator-edited HTML is preserved. The
thank-you Email Template is create-only and is never refreshed after insertion.
To adopt a later shipped Print Format after customizing it, review the new
shipped body and apply or replace the local version manually.

## Saved Recipient Selections

Open **Recipient Selections → NPO Recipient Selection** to save a reusable,
channel-neutral audience. Only **Non Profit Manager** and **System Manager** can
manage these records.

1. Enter a unique **Selection Name** and keep **Enabled** selected while the
   audience may be used. The name becomes the stable campaign source key and
   cannot be renamed later.
2. Enable Newsletter, Direct Mail, or both under **Available Channels**.
3. Enable at least one source: Contacts, Members, or Donors.
4. Optionally restrict Contacts to one exact Tag, Members by Membership Type,
   Status, and active date, or Donors by Donor Type.
5. Save. **Canonical Candidates** counts unique Contact, Customer, or explicit
   Household identities, not source rows; one person who is both Member and
   Donor counts once.
6. Use **Actions → Preview Recipients** to inspect up to 50 labels, email and
   language results, and whether a complete postal address can be resolved. The
   preview never displays the postal address itself.

Contact sources include person Contacts only. Member selection uses Membership
validity on **Membership Active On** and resolves Member Contact before Customer.
Donor selection uses an explicit or compatible legacy Household subject first,
then an Individual Contact; Organization uses Customer, and blank legacy subjects
may use Contact or Customer. Unsupported identities fail closed even if stale
links remain, and Generic Endpoint Contacts never become recipients. Evaluation
and correspondence enrichment use normal row-level permissions and ask you to
narrow the filters if more than 10,000 raw source rows match.

Use **Actions → Create Channel Campaigns** to create a Newsletter draft, Direct
Mail draft, or both from one saved source. The dialog shows only installed and
enabled channels that you are permitted to create. Enter one shared title and
optional Donation Campaign, then complete each selected channel's section;
unselected channel fields are neither shown nor required. Newsletter creates a
fresh private Audience and defaults to Pending opt-in; clear that option only
when an existing consent or relationship permits mailing. Direct Mail requires
a reusable Letter Template and output configuration, then opens as Draft for
preparation/review.
Both drafts record the same launch-time source fingerprint; Direct Mail refuses
preparation if the selection or its evaluated source rows changed afterward.

The same selection remains available from the Good Newsletter Audience import
dialog. Candidates with no reachable email are reported as skipped instead of
silently disappearing. Contact opt-outs are excluded and duplicate email
addresses are collapsed case-insensitively.

The count and **Last Evaluated On** are refreshed when the selection is saved.
Source data may change later; save the selection again before comparing its
stored count, and let the consuming campaign create its own current snapshot.

## Person-Level Contact Suppression

Create an **NPO Contact Suppression** when a person must not be contacted on
any channel — typically after a death notice or an explicit do-not-contact
request. Only **Non Profit Manager** and **System Manager** can manage these
records.

1. Select the person's **Contact** (Members and Donors are matched through
   their canonical Contact automatically).
2. Choose the **Scope**: `Deceased` or `Do Not Contact`.
3. Optionally record the **Date** and a **Reason** for the audit trail.
4. Save. Installed campaign apps exclude the person during their next
   recipient preparation or send; existing frozen postal snapshots and
   already-queued emails are not rewritten.
5. To retire a mistaken entry, clear **Active** instead of deleting the row so
   the history remains.

A contact suppression does not replace channel-specific opt-outs (newsletter
unsubscribes, bounce suppression, postal suppressions). It is an additional
person-level block on top of them.

## Donations

Use **Donor** (Spender), **Donation Campaign** (Spendenkampagne), **Donation** (Spende), and **Donation Tax Receipt** (Spendenbescheinigung) for fundraising workflows.
Donation Campaign forms show a year-selectable donation chart above linked
donations. The chart is hidden on unsaved campaigns, clears stale chart sections
when switching between campaigns, and each stacked segment opens the underlying
paid Donation. Its axis/grid and bar baseline share the same plot height, the
chart stretches to the full form dashboard width, and month columns shrink inside
the form so the chart does not push the Desk page sideways on mobile. Changing
the chart year keeps the mobile scroll position stable.

Public donation forms must submit donor name, a valid email, positive amount,
consent, and an allowed frequency. A public campaign must be active and use an
enabled leaf Cost Center belonging to the server-resolved Donation Company;
cross-Company, group, disabled, and unassigned Cost Centers are rejected. Keep
those checks server-side in `non_profit.www.donate._handle_submission`; browser
validation is only a convenience. Guest identity lookup/creation is serialized
by normalized email through commit or rollback. The lock renews during a long
transaction and is checked again before commit; if the request reports that
identity serialization expired, no identity write was committed and the user
can retry. Guest POSTs are rate-limited and always
require GoodVantage CAPTCHA. Install Good Connector and configure both CAPTCHA
keys before exposing `/donate`; missing or unreadable configuration blocks
submission instead of creating Donor/Donation records without bot protection.
The submit button remains disabled until the CAPTCHA loader succeeds. If loading
fails, use the displayed **Retry** action; the button is enabled only after that
retry reaches the loaded state, and server-side token verification remains the
authoritative gate.

Use **Donor.customer** to connect fundraising contacts to ERPNext Customer data.
Customer linkage is handled by creation, import, and repair helper flows rather
than a separate Donor form action. The helper reuses a Customer already linked
to a Member with the same email before creating a new Customer, then links
Contact and Address rows to both Donor and Customer. For an individual Donor,
the hidden canonical Contact field is persisted as well.
When creating a Donor from Desk, use the Contact/Customer dialog to select a
Contact, a Customer, or both. Contact-only Donors stay linked to the Contact
without forcing Customer creation; selecting a Customer links both Contact and
Customer when both are provided. Sponsor creation uses the same identity flow and
creates/reuses the backing Donor before opening the Sponsor; Contact links are
saved through the parent Contact so Frappe validates the child rows correctly.
These helpers require create permission for the target record and write
permission on selected Contact/Customer records before links are appended.
Volunteer creation is Contact-only and deliberately does not create or link a
Customer. Person-role helpers accept a blank legacy Contact classification and
set it to **Person**, but reject a Contact explicitly classified as a generic
endpoint/shared mailbox.
Donor email is not stored on Donor. Individual Donors use their canonical
Contact email first; organization or legacy Donors fall back to the linked
**Customer** (`Customer.email_id`) and then a linked Contact. Donation,
and Recurring Donation rows keep an email
snapshot for operations and correspondence; Donation Tax Receipt email issuance
resolves the address live from the Donor chain instead of storing a snapshot. For existing records, run
`non_profit.non_profit.doctype.donor.donor.backfill_donor_customers` with
`bench execute` when you intentionally want to create/link Customers for older
Donors.
Public/presentation integrations should resolve a Donor and linked Customer
through
`non_profit.non_profit.donor_identity.resolve_donor_customer_identity()` rather
than copying email lookup and Customer creation. Use
`ambiguous_email_policy="reject"` for guest-facing flows so duplicate Donor or
Customer identities are sent to staff review instead of being merged arbitrarily.
Use the Frappe **Language** selector for Donor preferred language. The saved
value is still the language code, for example `de` or `en`, but operators get the
standard enabled-language lookup. `Donation Tax Receipt.language` is a plain
Select of the languages the app supports for correspondence (`de`, `fr`, `it`,
`en`), defaulting to `de`.

`Donation.thank_you_sent` is a standard field for **Verdankungen**. It is set automatically when `Donation.send_thank_you()` queues an email and can also be used by presentation apps for manual acknowledgement queues. `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` keep the audit trail.

A **Verdankung** (thank-you for one donation) and a **Spendenbescheinigung**
(annual tax receipt) are different documents. Verdankungen live on the Donation;
Bescheinigungen live on **Donation Tax Receipt** — see
[Annual Donation Tax Receipts](#annual-donation-tax-receipts-spendenbescheinigungen).
The older `Donation Receipt` DocType was a second Bescheinigung model and was
removed in 16.10.0.

When a payment gateway authorizes a Donation, `Donation.on_payment_authorized()`
marks the Donation paid and, when enabled, creates the configured automatic
Payment Entry. If Payment Entry creation or submission fails, the base
`non_profit` controller resets the paid flag, logs the error, and raises; it does
not send the thank-you from that failed authorization attempt. Presentation apps
customize only the post-accounting thank-you dispatch seam; they do not replace
the settlement state machine or the Donation-owned thank-you audit write.

Legacy `Membership.generate_invoice()` / Membership Payment Entry methods and
Donation gateway-object helpers remain callable for compatibility, but every use
is written to the `non_profit.compatibility` logger. Treat those warnings as the
telemetry for migration planning; do not build new callers on these methods.
Compatibility facades remain for at least 90 days after telemetry deployment
and one complete release cycle with zero calls before removal is considered.

When an operator uses **Create Payment Entry** from a submitted unpaid Donation,
the draft shows only the amount left after submitted allocations. A second
partial allocation can settle the remainder, but fully allocated Donations and
stale drafts are rejected. Submission also requires the Payment Entry company
to match the Donation company and the Donor side to use the configured Donation
Debit Account for that company, or the derived Donor party account when no
company-valid Donation Debit Account is configured. Cancelling the Payment Entry
recalculates the Donation paid flag from the remaining submitted Payment Entries.
Submission uses current locking reads for Donation/account/allocation state, so
two concurrent full allocations cannot both pass from stale database snapshots.

Audit historical Donation accounting invariants without changing data:

```bash
cd frappe-bench
bench --site development16.localhost execute non_profit.non_profit.custom_doctype.payment_entry.audit_donation_payment_entry_invariants
```

Review every reported over-allocation, company mismatch, or Donor-account
mismatch manually with Accounting. Use normal ERPNext cancellation/reversal and
replacement documents; never repair submitted Payment Entries or ledger rows by
direct database updates. The audit compares against current account
configuration, so verify the configuration effective at the original posting
date before correcting historical entries.

The seeded **Donation Slip CH** Print Format renders the donation summary first
and places the Swiss QR-bill at the bottom of a separate final page. QR data is
prepared by the Donation controller before print rendering; do not add QR
generator calls directly to editable Jinja templates.

For automatic EBICS matching, install Good Connector and configure **Good
Connector Settings → EBICS Bank Integration** with the receiving Bank Account
and Mode of Payment. A submitted Donation receives a Donation-namespaced
27-digit QR reference; an already stored valid legacy reference is preserved. To
put that reference on the Donation Slip CH, the Non Profit creditor account must
be the exact QR-IBAN issued by the bank; an ordinary IBAN cannot carry QRR.
Automatic Donation matching supports only the Company currency: the receiving
bank Account and expected Donor receivable Account must use that same currency.
Foreign-currency cases remain **Review** for manual accounting.
The system also keeps overpayments and other unsafe exact Donation identities as
review candidates, so an invoice provider cannot silently claim the same QRR.
Donation candidate discovery is a side-effect-free ordered read; Good Connector,
not the provider, locks the selected eligible target before building a Payment
Entry.
New references are checked against active same-company Donations and Sales
Invoices; resolve any collision before issuing the slip.
Enable automatic reconciliation only after testing Donation, Sales Invoice, no
match, duplicate match, cross-domain match, partial payment, and overpayment
examples. Any zero or multiple aggregate match stays **Review** in the Bank
Transaction.

Credit card payments have two separate states. **Paid** means the gateway
confirmed the transaction and a submitted Payment Entry covers the Donation.
**Reconciled** means the submitted Payment Entry has been cleared through
ERPNext bank reconciliation, which sets `Payment Entry.clearance_date`.
`Donation.reconciled`, `reconciled_on`, and `reconciled_payment_entry` are
read-only operational mirrors of that accounting state. Use a gateway clearing
account as the Payment Entry target when card payouts settle later or net of
fees, then reconcile imported bank or payout transactions in ERPNext.

The legacy donation mock payment button is disabled by default. It only works
on developer sites when both `developer_mode` and
`enable_non_profit_mock_payments` are enabled in `site_config.json`. Production
sites should use a real payment integration such as `payrexx_integration`,
which verifies the provider callback before calling the Donation payment hook.
The mock endpoint is POST-only.

For multi-company benches, make sure the Donation's Mode of Payment has a
default account row for the Donation company. Global accounts in **Non Profit
Settings** are ignored when they belong to a different company.

## Annual Donation Tax Receipts (Spendenbescheinigungen)

**Donation Tax Receipt** holds one annual receipt per Donor, calendar tax year,
and Company. Since 16.10.0 it is the app's only Bescheinigung; the older
submittable `Donation Receipt` was removed. It feeds two dispatch paths: the
annual postal batch through `good_direct_mail`, and individual email issuance
straight from the receipt form.

Qualifying donations are submitted **and paid**, belong to the selected CHF
Company, are dated inside the calendar year, have an amount above zero, and name
a Donor. The operator must have read/User Permission access to that Company;
generation fails rather than aggregating a Company hidden from the current user.

1. **Generate.** Run `non_profit.non_profit.tax_receipts.generate_receipts`
   with the Company and tax year. It creates a Draft receipt per Donor and
   returns `{created, updated, deleted, unchanged, stale_issued}`. Generation
   locks the existing Company row before re-reading current Donations and
   receipts, so concurrent and empty first runs use the same safe serialization.

   ```bash
   bench --site <site> execute non_profit.non_profit.tax_receipts.generate_receipts \
     --kwargs '{"company": "Example AG", "tax_year": 2026}'
   ```

2. **Review the Drafts.** Check totals and donation counts in the Donation Tax
   Receipt list. Re-running the generation is safe and idempotent: unchanged
   receipts are left alone and Drafts are refreshed. A stale Draft whose donor
   has no remaining qualifying Donation is deleted and counted under `deleted`.
   Any name listed under
   `stale_issued` is an already-issued receipt whose donations changed
   afterwards — handle those manually; the service never rewrites an issued
   receipt silently. Statuses cannot be edited by hand; only the service moves a
   receipt between Draft, Issued, and Cancelled.

3. **Create the letter campaign.** Run
   `non_profit.non_profit.tax_receipts.create_receipt_campaign` with the
   Company, tax year, and a Letter Head (optionally a Print Format, letter
   title, letter body, and an explicit Company Address). It regenerates the
   receipts first and then opens a `Good Direct Mail Campaign` with letter
   category **Official**, no payment part, and a German letter carrying
   `{{ salutation }}`, `{{ receipt_total }}`, `{{ donation_count }}`,
   `{{ tax_year }}`, and the pre-built `{{ donation_table_html }}` table.
   Requires System Manager or Direct Mail Manager, and `good_direct_mail` to be
   installed. The service rejects a second non-cancelled receipt Campaign for
   the same Company/year; continue the existing Campaign or cancel it before
   deliberately creating a replacement.

4. **Run the campaign in Good Direct Mail.** Prepare, review address failures,
   freeze, generate, and post the batch exactly as for any other campaign (see
   good_direct_mail's `HOW_TO.md`). Donors without a resolvable canonical postal
   subject never reach the campaign and are logged during preparation.

5. **Mark the receipts issued.** After the batch is posted, run
   `non_profit.non_profit.tax_receipts.mark_receipts_issued` with the same
   Company and tax year. With no `receipt_names`, it marks only Draft receipts
   with a canonical postal subject; subjectless receipts that could not enter
   direct mail stay Draft. Prefer passing the exact posted receipt names as a
   JSON list when taking them from Campaign review. It sets those Drafts to
   Issued with today's date and returns how many changed. Issued receipts are no
   longer returned by the direct-mail provider, preventing an accidental second
   postal batch.

   ```bash
   bench --site <site> execute non_profit.non_profit.tax_receipts.mark_receipts_issued \
     --kwargs '{"company": "Example AG", "tax_year": 2026, "receipt_names": ["NPO-STR-2026-00001"]}'
   ```

### Cancelling an incorrect receipt

Open a Draft or Issued Donation Tax Receipt and use **Actions →
Spendenbescheinigung stornieren**, then enter the required reason. The POST-only
service records **Cancelled On**, **Cancelled By**, and **Cancellation Reason**;
these fields and the status cannot be edited directly. Repeating cancellation
does not overwrite the original audit. A Cancelled annual donor/year/company
receipt is never regenerated because that key is intentionally retained as the
correction record; a replacement/amendment model remains a separate future
decision.

The equivalent command is:

```bash
bench --site <site> execute non_profit.non_profit.tax_receipts.cancel_receipt \
  --kwargs '{"receipt": "NPO-STR-2026-00001", "reason": "Donation refunded"}'
```

### Sending one receipt by email

Open the Donation Tax Receipt and use **Actions → Spendenbescheinigung per
E-Mail senden**. The seeded **Spendenbescheinigung** Print Format is rendered to
PDF and emailed to the donor; the send is recorded on the receipt timeline and
`Email Sent On` is stamped.

- Only **Draft** and **Issued** receipts can be emailed.
- **Emailing does not issue the receipt.** The status stays what it was;
  `mark_receipts_issued` remains the explicit action that closes an annual run.
  This lets you send a courtesy copy of a Draft without pretending the batch
  went out.
- You need read access to the receipt **and** the *Email* permission on
  Donation Tax Receipt. Demo users are deliberately denied that permission.
- The address comes from the Donor's canonical Contact, then the linked
  Customer, then a linked Contact. If none of those has an email, the action
  fails with a clear message — fix the Donor identity rather than typing an
  address into the receipt.

You can also call it from a script:

```bash
bench --site <site> execute non_profit.non_profit.tax_receipts.send_receipt_email \
  --kwargs '{"receipt": "NPO-STR-2026-00001"}'
```

Still open and deliberately not implemented: minimum-amount and in-kind /
membership-fee refinements to the qualifying rules, cantonal receipt format
variations, the signature image on the receipt letter, and fr/it/en print
formats (`language` already records the intent).

## Memberships

Use **Member** as the canonical identity and **Membership** for membership
periods and billing. This fork supports both B2C membership via
`Membership.member` and B2B workflows where a Member can be linked to a
Customer. The linked Customer is the place to inspect the business or
organisation context; `Membership.company` was removed and must not be used as
an operator-maintained member company. Membership invoices and subscriptions
resolve their accounting company from **Non Profit Settings**.
Membership Type, Status, and validity dates live on **Membership** only; the
Member form does not store its own Membership Type. If an older site still has
the legacy `membership_expiry_date` field on Member, the Desk form refreshes it
from Membership as a display sync without marking the Member form dirty.
The legacy **Generate Invoice** action is only shown on sites that still carry a
`Membership.invoice` link field. Current downstream membership billing may use
Sales Invoice links owned by the presentation app instead.

When **Send Membership Acknowledgement** is enabled in Non Profit Settings, a
saved Membership exposes **Actions → Send Acknowledgement**. It sends the
configured Email Template and Membership Print Format and may include the linked
legacy invoice print. Verify those templates before enabling the action.

Operators may edit **Member Name** directly. When it is left blank and a
Customer is linked, the Member form fills it from that Customer; if the Customer
has a `name_additional` field, it is appended to the display name.

To create a complete member identity from Desk:

Good Connector must be installed for this guided raw-data dialog. A standalone
Non Profit site without Good Connector keeps the technical Contact/Customer
selector.

1. Open **Member** and choose **Add Member** / **Mitglied anlegen**.
2. Select **Individual / Privatperson** or **Organization / Organisation**.
3. Optionally select an existing Contact and/or Address. Their identity fields
   are filled and locked so the selected master data is linked without being
   overwritten. Clear a selector to enter new data instead.
4. For an Individual, enter first name, last name, email, optional phone,
   street/house number, postal code, city, country, Membership Type, and From
   Date. Country starts with the site default.
5. For an Organization, enter its name. The address is optional but street,
   postal code, and city must be entered together. A contact person is optional;
   when used, enter the real person's first name, last name, and email (phone is
   optional). Never enter the foundation/company itself as the contact person.
6. Choose **Create**. On success Desk opens the resulting Member.

The action safely creates or reuses Contact, Address, Customer, and Member. It
creates a new Current open-ended Membership or reuses an existing active Current
period without rewriting its configured dates. For a person, the Contact is the canonical
`Member.contact`. For an organization, the Customer/Member represents the
organization while an optional human Contact remains a separate correspondence
link. An Organization Customer's existing primary Contact is retained when an
additional correspondence person is linked. If Desk reports multiple Contacts,
Members, Customers, organization names, exact Addresses, or an active non-Current
Membership, stop and resolve those records manually; the dialog deliberately does not guess or merge. A same-email Customer
that is not already linked to the resolved Contact is not adopted. Billing
Address metadata is an operational address type and must not be interpreted as
postal consent.

Users need create, read, and write permission for Contact, Address, Customer,
Member, and Membership, plus read permission for Membership Type and Country.
The action creates no Subscription, invoice, acknowledgement, or confirmation
email. Public signup billing remains a downstream workflow.

From a saved Member, use **Actions → Create Membership** to create or open the
active open-ended Membership for that Member and chosen Membership Type. Existing
integrations may continue using the technical Contact/Customer endpoint; its
arguments and response contract are unchanged.

Leave **Membership Until** empty for a perpetual/open-ended membership. If code
creates the Membership and must intentionally keep **Membership Until** blank, set
`membership.flags.keep_to_date_open = True` before insert.

Only enable **Is Subscription** on **Membership Type** when memberships of that
type should create/link ERPNext Subscriptions automatically. Leave it disabled
for declaration or data-collection memberships that are billed after a separate
declaration process. To bill an open-ended
membership through ERPNext subscriptions, use
`non_profit.non_profit.membership_subscription.ensure_membership_subscription`;
it only creates a Subscription for subscription-enabled Membership Types, links
`Membership.subscription`, and leaves **Membership Until** open.

If `good_connector` is installed, legacy member registration creates/reuses the
linked Contact through Good Connector identity matching. Review possible fuzzy
matches in **GC Potential Duplicate** instead of expecting automatic merges.

Donor, Member, and Company records do not store PAN/tax-id details. Migrate
removes the legacy Donor/Member PAN custom fields, Company PAN/80G fields, and
India-specific 80G certificate DocTypes instead of only hiding them from the
form. Payment-note imports also skip PAN/tax-id keys before writing Donor
comments.

When changing Member or Membership behavior, run the relevant downstream
consumer tests too because they depend on this shared substrate.

The **Expiring Memberships** report reads the latest non-cancelled Membership
per Member and filters by its `to_date`. It no longer depends on the legacy
`Membership.paid` field.

## Households

Use **Household** for people who share a postal address and should be treated
as one unit for mailings — typically couples. Create one Household per address
unit and add each person's **Contact** in the **People** table with a **From
Date**; optionally record the relationship and tick **Is Primary** on the main
person. Leave **To Date** empty while the person belongs to the Household. A
Contact can belong to only one current Household; the form refuses a second.
Only **Non Profit Manager** users can view or edit Households because a
Household may expose both Member and Donor records.

- Marriage / new partner moves in: add a row with the **From Date**.
- Divorce / someone moves out: set **To Date** on that person's row. The row
  stays as history and every linked Member/Donor role's **Household** clears
  automatically.

Memberships of household members are flagged **Is Household Membership**
automatically (on save, and refreshed when household membership changes) for
reporting and downstream policy. The flag does not transfer one person's
membership coverage to everyone in the Household. Attach the shared address
and contacts through the standard **Address and Contact** section on the saved
Household form; the same Address/Contact can also be linked to the individual
Member, Donor, or Customer records. Customers also carry a **Household** link
field, and Contacts have a **Title** field for academic titles such as `Dr.`.
The Household fields on Member and Donor are read-only role projections; always
change the dated Contact rows on Household instead of editing those links.
Contacts explicitly classified as **Generic Endpoint** cannot be Household
people. **NPO Organization** and the hidden Customer/Supplier identity fields
are Stage 1 data anchors; no operator merge workflow is shipped yet.

Set **Preferred Language** on a Contact for individual correspondence. Set it
on Household when people in that Household should receive shared mail in one
language; the current Household preference takes precedence over Donor,
Customer, and Contact language when correspondence is resolved. Leave the field
blank when staff must choose the language in the sending workflow rather than
recording an assumed default.

Postal integrations that already consolidated an audience should send the
canonical Contact, Customer, or Household plus the related Contact, Member,
Donor, and Customer names to the correspondence resolver. Related Donor,
Customer, and Contact language/address data is considered, but it cannot replace
the supplied canonical subject. Pass actual name lists, not a single string.

Keep only usable postal Addresses active and link a shared address directly to
the Household. The correspondence resolver accepts a sole candidate, a unique
explicit Contact/Customer address pointer, or one uniquely primary Address. If
a profile reports `MISSING_ADDRESS`, add/link the correct Address. If it reports
`AMBIGUOUS_ADDRESS`, review the linked active Addresses and disable/unlink an
obsolete link or set the intended unique primary; the resolver deliberately
does not choose the first row. Never edit a shared Address automatically from a
returned-letter workflow.

Integrations that need joint donation attribution must call
`get_or_create_donor_for_household()` and use the resulting Donor on Donation.
Do not assign the Donation arbitrarily to the primary person and do not create a
Household Customer: Household is already the canonical solicitation subject,
and Donor is the existing Donation/Payment Entry party. A unique legacy Donor
with the same **Subject Household** and blank **Subject Type** is reused; if more
than one canonical/legacy candidate exists, resolve the duplicate records before
retrying.

## Recurring Donations

Use **Recurring Donation** for a schedule, not as proof of payment. A due active
row creates a submitted, unpaid Donation in the daily job, advances **Next
Date**, and becomes Cancelled once the next date passes **End Date**. Accounting
or a payment provider must settle each generated Donation separately. The job
serializes each schedule and reuses an already-created installment for the same
schedule/date, so retries or overlapping workers do not create duplicates.

**Actions → Create Next Donation Now** creates an installment immediately and
also advances the schedule. It is available only while no payment provider owns
the schedule.

The public `/donate` page offers one-off and monthly. When a payment
integration is installed it owns the whole path: the donor is redirected to a
hosted checkout and the gift is collected. With no integration installed the
page records the gift and collects nothing — the historical behaviour.

Donors are emailed at three moments only: when the mandate is confirmed, when a
payment has finally failed (not while the provider is still retrying), and when
the schedule is stopped. Each successful installment gets the normal Verdankung,
and the annual Bescheinigung aggregates them as it does any other paid donation.

### Provider-backed schedules

When a payment integration owns a schedule, the **Payment Provider** section is
filled in and the provider — not this app — decides when to charge. The daily
job skips it entirely; installments appear as **paid** Donations when the
provider reports each charge. Provider-owned Company, status, amount, currency,
frequency, and linkage cannot be edited directly; use the supported actions.
If the provider section is incomplete, amount change and ordinary cancellation
stop for repair instead of applying a local-only change; abandoned-checkout
retirement remains available only through explicit provider verification.

- **Actions → Change Amount** applies from the provider's *next* charge, never
  the one already taken.
- **Actions → Cancel Schedule** stops future charges immediately. There is no
  grace period, and a cancelled schedule cannot be resumed — create a new one.
- **Actions → Retire Abandoned Checkout** appears for an incomplete **Pending
  Mandate**. It asks the registered provider to prove that no payment or mandate
  can still exist and changes the row only after positive proof. If verification
  is unavailable or inconclusive, leave the row open and inspect the provider;
  do not clear provider fields or cancel it locally.
- **Payment Retrying** means a charge failed and the provider will try again.
  Nothing is required from you yet.
- **Payment Failed** means the provider gave up. This one needs attention.
- **Ending** means the donor cancelled but the remaining charges still follow,
  so installments keep arriving until the term ends.

**Payment Failed** and **Cancelled** are terminal. A delayed active/retrying
event cannot reopen them; create a new schedule when the donor starts again.

If an amount change or cancellation reports an error after the provider already
answered successfully, do not issue a different operation. Retry the exact same
action and value: provider integrations must make these operations idempotent
and journal `local_commit_pending`, `local_commit_confirmed`, or
`local_rollback_confirmed` with the schedule, provider account, subscription,
and requested action. An unpaired pending entry means local commit is unknown;
verify the provider state and retry the same action until a commit-confirmed
entry appears.

**Paused** no longer exists. No provider offers a pause, and the gated daily job
could not honour one; existing paused schedules were migrated to Cancelled.
The migration adds a timeline note. Create a new schedule to restart giving.

## Chapters And Grants

Logged-in users can join a published Chapter only as themselves through the
public join page. Chapter members can only leave their own active membership
through the public leave endpoint. Staff changing another user's chapter row
need write permission on the Chapter. Grant review invitations require write
permission on the Grant Application and an Assessment Manager before the status is moved to
**In Progress**. Published grant pages do not render applicant email.

Create Volunteers from an existing Contact; the dialog requires a Volunteer Type
and an email on the Contact. It does not create a Customer. Create Sponsors from
a Contact, Customer, or both; the system creates or reuses the backing Donor and
fetches the Sponsor name from it.

Logged-in applicants use `/my-grant`. Staff set an Assessment Manager and use
**Actions → Send Grant Review Email** while the application is **Received**;
the action sends the invitation and moves it to **In Progress**.

## Major Gifts — Next Actions

A **Major Gift** is one concrete cultivation ask. Relationship and ask notes go
into the native timeline comments on the Donor or Major Gift. When Workflow Visualizer is installed, saved Major Gift forms show
the pipeline stages and permitted Back/Proceed actions above the form. New,
unsaved records show the pipeline after their first save. Non Profit owns this
opt-in and re-enables **Visible on Doctype** during setup/migrate if it is
cleared. The "next action" on either record is tracked as a real **Task**, not a
text note:

- Record **First Contact / Inquiry Channel** as Email, Letter, Phone, Website
  Form, or Other.
- **Mark Won** and **Mark Lost** open a required dialog. Enter the reason to
  complete the workflow transition.
- To track only a date, enter **Follow-up Date** directly while no open Task is
  linked. The date is also shown in the Major Gift list.

1. Open a Donor or Major Gift and choose **Actions → Set Next Action**.
2. Enter the action, a due date, and who to assign it to (defaults to the gift's
   or donor's Relationship Manager), then **Create Task**.

The Task is created, assigned (the assignee gets it in their To-Do list), and
linked back. The record's **Next Action**, **Follow-up Date**, and **Next Action
Task** fields reflect the earliest *open* linked Task, and
update automatically when you complete or reschedule that Task (mark the Task
**Completed** and the next action advances to the next open Task, or clears).
All linked Tasks are listed under the form's **Connections** tab. A Major Gift
Task links to both the gift and its Donor, so the Donor shows the earliest open
relationship or gift Task. Requires write access to the Donor or Major Gift.
While an open Task is linked, its due date controls **Follow-up Date** and the
field cannot be edited on Major Gift. Completing the final open Task clears the
date; enter a new manual date afterwards if no replacement Task is needed.

The reduced workflow is **Qualification → Cultivation → Solicitation → Won**.
Use **Mark Lost** from any open stage and **Reopen** to return a lost ask to
Qualification. Won asks stay closed; create a new Major Gift for a later ask.
After linking a Donation or Task, the Major Gift's Donor cannot be changed;
create a corrected Major Gift instead.

The daily fundraising reconciliation repairs Donor giving summaries and Major
Gift closed amounts from submitted, paid Donations. It processes all records in
grouped batches and writes only changed summaries; the fields and latest-gift
policy shown to operators are unchanged.

## Smoke Checks

```bash
cd frappe-bench
bench --site development16.localhost execute non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures
bench --site development16.localhost run-tests --app non_profit
```
