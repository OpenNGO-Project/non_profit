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

Use **Donor**, **Donation Campaign**, **Donation**, and **Donation Receipt** for fundraising workflows.

`Donation.thank_you_sent` is a standard field. It is set automatically when `Donation.send_thank_you()` queues an email and can also be used by presentation apps for manual acknowledgement queues.

When a payment gateway authorizes a Donation, `Donation.on_payment_authorized()`
marks the Donation paid first. If automated Payment Entry creation is enabled
but account configuration is incomplete, the accounting failure is logged and
does not roll back the paid state or thank-you dispatch.

For multi-company benches, make sure the Donation's Mode of Payment has a
default account row for the Donation company. Global accounts in **Non Profit
Settings** are ignored when they belong to a different company.

## Memberships

Use **Member** as the canonical identity and **Membership** for membership periods and billing. This fork supports both B2C membership via `Membership.member` and B2B workflows where a Member can be linked to a Customer.

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

When changing Member or Membership behavior, run the relevant `miki_app` tests too because Miki depends on the shared membership substrate.

## Smoke Checks

```bash
cd frappe-bench
bench --site development16.localhost execute non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures
bench --site development16.localhost run-tests --app non_profit
```
