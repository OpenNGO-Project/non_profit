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

## Donations

Use **Donor** (Spender), **Donation Campaign** (Spendenkampagne), **Donation** (Spende), and **Donation Receipt** (Spendenbescheinigung) for fundraising workflows.

Public donation forms must submit donor name, a valid email, positive amount,
consent, an allowed frequency, and only active Donation Campaigns. Keep those
checks server-side in `non_profit.www.donate._handle_submission`; browser
validation is only a convenience. Guest POSTs are rate-limited. When
`good_connector` provides a GoodVantage CAPTCHA site key, the form renders the
widget and the server verifies the CAPTCHA token before creating Donor/Donation
records.

Use **Donor.customer** to connect fundraising contacts to ERPNext Customer data.
Open a Donor and use **Actions → Create Customer** when the link is missing.
The helper reuses a Customer already linked to a Member with the same email
before creating a new Customer, then links Contact and Address rows to both
Donor and Customer.
Donor email is stored on the linked **Customer** (`Customer.email_id`), not on
Donor. Donation, Recurring Donation, and Donation Receipt rows keep an email
snapshot for operations and correspondence. For existing records, run
`non_profit.non_profit.doctype.donor.donor.backfill_donor_customers` with
`bench execute` when you intentionally want to create/link Customers for older
Donors.

`Donation.thank_you_sent` is a standard field for **Verdankungen**. It is set automatically when `Donation.send_thank_you()` queues an email and can also be used by presentation apps for manual acknowledgement queues. `thank_you_sent_on`, `thank_you_email_queue`, and `thank_you_sent_by` keep the audit trail. This is intentionally separate from `Donation.receipt`, which links to **Donation Receipt** / **Spendenbescheinigung** tax certificates generated yearly or ad hoc.

Yearly Donation Receipt generation is an operator action for users with
`Non Profit Manager` or `System Manager`. It creates draft receipts for
submitted, paid Donations in the selected fiscal year that do not already link
to a receipt; it does not commit mid-request, so Frappe can roll back the whole
operation if receipt creation fails. The default receipt country is
`Switzerland` on the form, yearly-generation dialog, and server fallback.

When a payment gateway authorizes a Donation, `Donation.on_payment_authorized()`
marks the Donation paid first. If automated Payment Entry creation is enabled
but account configuration is incomplete, the accounting failure is logged and
does not roll back the paid state or thank-you dispatch.

When an operator uses **Create Payment Entry** from a submitted unpaid Donation,
submitting the Payment Entry marks the Donation paid. Cancelling the Payment
Entry recalculates the Donation paid flag from the remaining submitted Payment
Entries for that Donation.

The seeded **Donation Slip CH** Print Format renders the donation summary first
and places the Swiss QR-bill at the bottom of a separate final page. QR data is
prepared by the Donation controller before print rendering; do not add QR
generator calls directly to editable Jinja templates.

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
Member form does not store its own Membership Type.

The Member form derives **Member Name** from the linked Customer. If the Customer
has a `name_additional` field, it is appended to the display name. Creating a new
Member opens a dialog where operators choose either a Contact or a Customer plus
the Membership Type; contact-only members are linked through Contact Dynamic
Links, not a Contact field on Member. The system creates/reuses the Member and
creates/reuses the open-ended Membership in one step. From a saved Member, use
**Actions → Create Membership** to create or open the active open-ended
Membership for that Member and chosen Membership Type.

Leave **To** empty for a perpetual/open-ended membership. If code creates the
Membership and must intentionally keep **To** blank, set
`membership.flags.keep_to_date_open = True` before insert.

Only enable **Is Subscription** on **Membership Type** when memberships of that
type should create/link ERPNext Subscriptions automatically. Leave it disabled
for declaration or data-collection memberships, for example MiKi memberships
that are billed after a separate declaration process. To bill an open-ended
membership through ERPNext subscriptions, use
`non_profit.non_profit.membership_subscription.ensure_membership_subscription`;
it only creates a Subscription for subscription-enabled Membership Types, links
`Membership.subscription`, and leaves the Membership **To** field open.

If `good_connector` is installed, legacy member registration creates/reuses the
linked Contact through Good Connector identity matching. Review possible fuzzy
matches in **GC Potential Duplicate** instead of expecting automatic merges.

Member and Company records do not store PAN/tax-id details. Migrate removes the
legacy Member PAN custom field, Company PAN/80G fields, and India-specific 80G
certificate DocTypes instead of only hiding them from the form.

When changing Member or Membership behavior, run the relevant `miki_app` tests too because Miki depends on the shared membership substrate.

The **Expiring Memberships** report reads the latest non-cancelled Membership
per Member and filters by its `to_date`. It no longer depends on the legacy
`Membership.paid` field.

## Chapters And Grants

Logged-in users can join a published Chapter only as themselves through the
public join page. Chapter members can only leave their own active membership
through the public leave endpoint. Staff changing another user's chapter row
need write permission on the Chapter. Grant review invitations require write
permission on the Grant Application and an Assessment Manager before the status is moved to
**In Progress**.

## Smoke Checks

```bash
cd frappe-bench
bench --site development16.localhost execute non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures
bench --site development16.localhost run-tests --app non_profit
```
