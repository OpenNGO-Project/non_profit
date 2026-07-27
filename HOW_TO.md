# Non Profit - How To

This bench uses `non_profit` as the shared fundraising and membership substrate for `ilanga_app`, `miki_app`, and Goodvantage NPO layers.

## Install Or Update

```bash
cd frappe-bench
bench --site development16.localhost install-app non_profit
bench --site development16.localhost migrate
```

ERPNext must already be installed.

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

### Currency and receipt jurisdiction

The generic `/donate` and `/donate_confirm` pages currently display **EUR**, and
the seeded `Donation Thank You DE` email also formats EUR. The separate
`Donation Slip CH` Swiss QR slip displays CHF. Donation has no currency field,
so these labels do not derive from the Donation Company. Production sites must
provide a locally approved, currency-aware presentation flow.

The seeded **Donation Receipt DE** contains German tax-law wording (`§ 10b EStG`
and related German provisions). Setting the receipt country to Switzerland does
not localize or legally approve that wording. Do not issue it as a Swiss tax
certificate. Install a jurisdiction-specific format approved by the responsible
organisation; this app intentionally does not invent Swiss legal text.

You may edit **Donation Receipt DE**, **Donation Slip CH**, and **Donation Thank
You DE** in Desk. Migrate updates a Print Format only while its HTML still
matches known app-shipped content; any operator-edited HTML is preserved. The
thank-you Email Template is create-only and is never refreshed after insertion.
To adopt a later shipped Print Format after customizing it, review the new
shipped body and apply or replace the local version manually.

## Donations

Use **Donor** (Spender), **Donation Campaign** (Spendenkampagne), **Donation** (Spende), and **Donation Receipt** (Spendenbescheinigung) for fundraising workflows.
Donation Campaign forms show a year-selectable donation chart above linked
donations. The chart is hidden on unsaved campaigns, clears stale chart sections
when switching between campaigns, and each stacked segment opens the underlying
paid Donation. Its axis/grid and bar baseline share the same plot height, the
chart stretches to the full form dashboard width, and month columns shrink inside
the form so the chart does not push the Desk page sideways on mobile. Changing
the chart year keeps the mobile scroll position stable.

Public donation forms must submit donor name, a valid email, positive amount,
consent, an allowed frequency, and only active Donation Campaigns. Keep those
checks server-side in `non_profit.www.donate._handle_submission`; browser
validation is only a convenience. Guest POSTs are rate-limited and always
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
Contact and Address rows to both Donor and Customer.
When creating a Donor from Desk, use the Contact/Customer dialog to select a
Contact, a Customer, or both. Contact-only Donors stay linked to the Contact
without forcing Customer creation; selecting a Customer links both Contact and
Customer when both are provided. Sponsor creation uses the same identity flow and
creates/reuses the backing Donor before opening the Sponsor; Contact links are
saved through the parent Contact so Frappe validates the child rows correctly.
These helpers require create permission for the target record and write
permission on selected Contact/Customer records before links are appended.
Volunteer creation is Contact-only and deliberately does not create or link a
Customer.
Donor email is stored on the linked **Customer** (`Customer.email_id`), not on
Donor. Donation, Recurring Donation, and Donation Receipt rows keep an email
snapshot for operations and correspondence. For existing records, run
`non_profit.non_profit.doctype.donor.donor.backfill_donor_customers` with
`bench execute` when you intentionally want to create/link Customers for older
Donors.
Public/presentation integrations should resolve a Donor and linked Customer
through
`non_profit.non_profit.donor_identity.resolve_donor_customer_identity()` rather
than copying email lookup and Customer creation. Use
`ambiguous_email_policy="reject"` for guest-facing flows so duplicate Donor or
Customer identities are sent to staff review instead of being merged arbitrarily.
Use the Frappe **Language** selector for Donor preferred language and Donation
Receipt language. The saved value is still the language code, for example `de`
or `en`, but operators get the standard enabled-language lookup.

`Donation.thank_you_sent` is a standard field for **Verdankungen**. It is set automatically when `Donation.send_thank_you()` queues an email and can also be used by presentation apps for manual acknowledgement queues. `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` keep the audit trail. This is intentionally separate from `Donation.receipt`, which links to **Donation Receipt** / **Spendenbescheinigung** tax certificates generated yearly or ad hoc.

Yearly Donation Receipt generation is an operator action for users with
`Non Profit Manager` or `System Manager`. It creates draft receipts for
submitted, paid Donations in the selected fiscal year that do not already link
to a submitted receipt or another active draft receipt; it does not commit
mid-request, so Frappe can roll back the whole operation if receipt creation
fails. The default receipt country is
`Switzerland` on the form, yearly-generation dialog, and server fallback.
Donation Receipts may also be saved before donation rows are added. On a draft
receipt, use **Actions → Spenden aus Geschäftsjahr hinzufügen** after choosing a
Donor and Fiscal Year to populate all unreceipted paid Donations from that year.
Submitting a receipt validates that every row is paid, submitted, in the selected
period, belongs to the receipt Donor, and is not already attached to another
active receipt. Large yearly runs load eligible Donations and active receipt
ownership in batches; the operator workflow and all validation rules are the
same as for an individual receipt.

The yearly action creates drafts only. Review donor, period, country, language,
donations, address, and the approved print format before submitting or sending.
The built-in **Spendenbescheinigung senden** action attaches `Donation Receipt
DE`; use it only where that German wording has been approved.

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
`Membership.invoice` link field. Current GoodNPO-style membership billing uses
Sales Invoice links owned by the presentation app instead.

When **Send Membership Acknowledgement** is enabled in Non Profit Settings, a
saved Membership exposes **Actions → Send Acknowledgement**. It sends the
configured Email Template and Membership Print Format and may include the linked
legacy invoice print. Verify those templates before enabling the action.

Operators may edit **Member Name** directly. When it is left blank and a
Customer is linked, the Member form fills it from that Customer; if the Customer
has a `name_additional` field, it is appended to the display name. Creating a
new Member opens a dialog where operators choose a Contact, a Customer, or both,
plus the Membership Type; contact-only members are linked through Contact
Dynamic Links, not a Contact field on Member. The system creates/reuses the
Member and creates/reuses the open-ended Membership in one step. From a saved
Member, use **Actions → Create Membership** to create or open the active
open-ended Membership for that Member and chosen Membership Type.

Leave **Membership Until** empty for a perpetual/open-ended membership. If code
creates the Membership and must intentionally keep **Membership Until** blank, set
`membership.flags.keep_to_date_open = True` before insert.

Only enable **Is Subscription** on **Membership Type** when memberships of that
type should create/link ERPNext Subscriptions automatically. Leave it disabled
for declaration or data-collection memberships, for example MiKi memberships
that are billed after a separate declaration process. To bill an open-ended
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

When changing Member or Membership behavior, run the relevant `miki_app` tests too because Miki depends on the shared membership substrate.

The **Expiring Memberships** report reads the latest non-cancelled Membership
per Member and filters by its `to_date`. It no longer depends on the legacy
`Membership.paid` field.

## Households

Use **Household** for people who share a postal address and should be treated
as one unit for mailings — typically couples. Create one Household per address
unit and add **Member** or **Donor** rows in the members table with a **From
Date**; tick **Is Primary** on the main contact. Leave **To Date** empty while
the person belongs to the household. A Member or Donor can be a *current*
member of only one household at a time; the form refuses to save a second one.
Only **Non Profit Manager** users can view or edit Households because a
Household may expose both Member and Donor records.

- Marriage / new partner moves in: add a row with the **From Date**.
- Divorce / someone moves out: set **To Date** on that person's row. The row
  stays as history and the person's **Household** link on Member/Donor clears
  automatically.

Memberships of household members are flagged **Is Household Membership**
automatically (on save, and refreshed when household membership changes), so
one shared membership can cover the whole household. Attach the shared address
and contacts through the standard **Address and Contact** section on the saved
Household form; the same Address/Contact can also be linked to the individual
Member, Donor, or Customer records. Customers also carry a **Household** link
field, and Contacts have a **Title** field for academic titles such as `Dr.`.
The Household fields on Member and Donor are read-only derived values; always
change the dated rows on Household instead of editing those links directly.

## Recurring Donations

Use **Recurring Donation** for a schedule, not as proof of payment. A due active
row creates a submitted, unpaid Donation in the daily job, advances **Next
Date**, and becomes Cancelled once the next date passes **End Date**. Accounting
or a payment provider must settle each generated Donation separately. The job
serializes each schedule and reuses an already-created installment for the same
schedule/date, so retries or overlapping workers do not create duplicates.

**Actions → Create Next Donation Now** creates an installment immediately and
also advances the schedule. Use **Paused** to stop generation without ending the
instruction.

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

A **Major Gift** is one cultivation "ask"; a **Donor Interaction** logs a
touchpoint. The "next action" on either is tracked as a real **Task**, not a
text note:

1. Open a Major Gift (or Donor Interaction) and choose **Actions → Set Next
   Action**.
2. Enter the action, a due date, and who to assign it to (defaults to the gift's
   Relationship Manager / the interaction's Staff), then **Create Task**.

The Task is created, assigned (the assignee gets it in their To-Do list), and
linked back. The record's read-only **Next Action**, **Next Action Date**, and
**Next Action Task** fields always reflect the earliest *open* linked Task, and
update automatically when you complete or reschedule that Task (mark the Task
**Completed** and the next action advances to the next open Task, or clears).
All linked Tasks are listed under the form's **Connections** tab. A next action
added on a Donor Interaction that belongs to a Major Gift also shows on that
gift. Requires write access to the gift/interaction (Non Profit Manager).

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
