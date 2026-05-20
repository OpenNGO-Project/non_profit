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
- **Donor**, **Donation**, **Donation Campaign**, **Recurring Donation**, and **Donation Receipt** for fundraising.
- **Sponsor**, **Sponsor Tier**, **Volunteer**, and **Grant Application** for broader NPO operations.
- **Non Profit Settings** for company, donor type, billing, invoicing, payment, webhook, and email defaults.

## Hooks

- `after_install = non_profit.setup.setup_non_profit`
- `after_migrate = non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures`
- `doc_events["Membership"]["validate"] = non_profit.non_profit.membership_sync.validate_no_overlap`
- Daily scheduler jobs expire memberships and process recurring donations.
- `Payment Entry` is extended through `override_doctype_class`.

## Donation Thank-Yous

`Donation.thank_you_sent` is a standard field on Donation. `Donation.send_thank_you()` queues the configured Email Template and marks this field once the email is queued. Presentation apps such as `ilanga_app` and `good_npo` read this field for pending thank-you queues.

`Donation.on_payment_authorized()` sets `paid = 1` before optional accounting
side effects. Automated Payment Entry failures are logged with the Donation
name and do not prevent thank-you dispatch. This keeps hosted-checkout webhooks
from being rolled back by single-company account settings on multi-demo sites.
Global `Non Profit Settings` accounts are applied only when the configured
Account belongs to the Donation company, so one company's legacy settings do
not overwrite another company's party or bank accounts.

## Membership Compatibility

Miki uses:

- `non_profit.non_profit.membership_sync.get_customer_for_membership`
- `non_profit.non_profit.membership_sync.list_customer_memberships`
- Member/Customer links through `Member.customer`
- `Membership.member` as the canonical membership link

If any of these contracts change, adjust `miki_app` and run its membership-related tests.

## Test Commands

```bash
cd frappe-bench
bench --site development16.localhost run-tests --app non_profit
bench --site development16.localhost run-tests --module miki_app.tests.test_membership_sync
```

The local bench has a known ERPNext bootstrap issue that can make full non_profit tests exit non-zero after app tests pass when Customer naming settings drift. Treat that as local test-data state unless the failure points at non_profit code.
