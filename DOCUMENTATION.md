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
- **Sponsor**, **Sponsor Tier**, **Volunteer**, and **Grant Application** for broader NPO operations.
- **Non Profit Settings** for company, donor type, billing, invoicing, payment account, and email defaults.

## Hooks

- `after_install = non_profit.setup.setup_non_profit`
- `after_migrate = non_profit.non_profit.fundraising_setup.ensure_fundraising_fixtures` refreshes non_profit custom fields and fundraising fixtures.
- `before_tests = non_profit.non_profit.utils.before_tests` refreshes the same fundraising fixtures after the CI/test setup wizard creates a Company.
- `doc_events["Membership"]["validate"] = non_profit.non_profit.membership_sync.validate_no_overlap`
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
submitted, paid Donations without an existing receipt link. Donation Receipt
country defaults to `Switzerland` in DocType metadata, the yearly-generation
dialog, and the backend fallback when no country argument is supplied.
`DonationReceipt` email sending, chapter staff edits, and grant review
invitations require write permission on the target document. A portal user
leaving a Chapter may only disable their own active row; editing another user
still requires Chapter write permission.

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

## Donation Thank-Yous

Donor identity mirrors the Member/Customer pattern: `Donation.donor` points to a
Donor, and Customer-level CRM data resolves through `Donation.donor ->
Donor.customer`. Donor no longer stores its own email address; donor email is
read from `Donor.customer -> Customer.email_id` and copied onto Donation /
Recurring Donation / Donation Receipt rows as an operational snapshot.
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

## Membership Compatibility

Miki uses:

- `non_profit.non_profit.membership_sync.get_customer_for_membership`
- `non_profit.non_profit.membership_sync.list_customer_memberships`
- Member/Customer links through `Member.customer`
- `Membership.member` as the canonical membership link

If any of these contracts change, adjust `miki_app` and run its membership-related tests.

The **Expiring Memberships** report derives one row per Member from the latest
non-cancelled Membership (`MAX(to_date)`) and filters that date against the
selected month/fiscal year. Frappe v16 removed the old `Membership.paid`
assumption from this fork, so report queries must not reference it.

Memberships can be open-ended: callers that intentionally want no expiry set
`membership.flags.keep_to_date_open = True` before insert. This bypasses the
default billing-cycle `to_date` fill in the Membership controller.

Recurring billing is opt-in per **Membership Type** with the **Is
Subscription** checkbox. Leave it disabled for declaration or data-collection
flows such as MiKi, where billing is triggered by a later process after
customer data has been collected. The shared
`non_profit.non_profit.membership_subscription.ensure_membership_subscription`
helper returns without creating anything unless the Membership Type is marked as
a subscription. For subscription-enabled types, it creates or reuses an ERPNext
**Subscription Plan**, creates an open-ended ERPNext **Subscription** for the
linked Customer, writes `Membership.subscription`, and clears
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

## Test Commands

```bash
cd frappe-bench
bench --site development16.localhost run-tests --app non_profit
bench --site development16.localhost run-tests --module miki_app.tests.test_end_to_end
```

`non_profit.non_profit.utils.before_tests` also normalizes local ERPNext bootstrap
preconditions before the suite runs: it uses a short in-process test host URL,
renames fixed ERPNext test Customers when local Customer naming is set to naming
series, and pre-creates ERPNext test Addresses with `pincode` for Swiss benches
where that field is mandatory.
