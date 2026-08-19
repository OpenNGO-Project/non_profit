# Non Profit Architecture Decisions

This register records durable architecture decisions owned by `non_profit`.
Detailed current behavior remains in [DOCUMENTATION.md](DOCUMENTATION.md).
Bench-wide decisions are in the
[bench register](https://github.com/Benema3000/frappe_docker/blob/main/development/ARCHITECTURE_DECISIONS.md).

## Maintenance

- Add a numbered decision for durable domain identity, dependency, public hook,
  accounting, or migration changes.
- Supersede accepted decisions instead of rewriting their history.
- Keep this public register free of private implementation details and aligned
  with `DOCUMENTATION.md`, requirements, and code.

## ADR-0001: Keep A Public NPO Domain Substrate With Neutral Extensions

- Status: Accepted
- Date: 2026-08-11
- Scope: `non_profit`
- Supersedes: None

### Context

Membership and fundraising facts are reused by multiple public and private
products. This repository is public, while most consumers are private. The base
must remain independently installable. An archived party-model plan also
described broader alternatives that were never shipped and are historical
context, not a prior ADR.

### Decision

Non Profit depends only on ERPNext and owns the generic NPO domain: canonical
Contact-backed people, NPO Organization identity, Households, Member and
Membership, Donor and Donation, recurring-donation evidence, campaigns,
channel-neutral recipient selections, major gifts, sponsors, volunteers,
grants, and the single `Donation Tax Receipt` model.

New private presentation, payment, analytics, newsletter, and postal behavior
enters through neutral hooks or services. Generic business rules stay here;
client branding, seeds, and UI stay downstream. The tax-receipt action that
late-resolves Good Direct Mail campaign creation is a documented legacy seam to
migrate, not a pattern for new private imports.

### Alternatives Considered

- Move the domain into a private Goodvantage app: rejected because it would
  break public reuse and invert existing dependencies.
- Let each consumer own its own Member/Donor model: rejected because identity,
  accounting, and correspondence would diverge.
- Add new private provider imports: rejected because they violate the public
  dependency boundary even when import failure is guarded.

### Consequences

- Public extension hooks must be named generically and fail closed.
- Downstream apps must coordinate when Member, Membership, Donor, Donation, or
  recipient-selection contracts change.
- ERPNext remains the operating/accounting master; Non Profit adds NPO identity
  and role semantics rather than replacing ERPNext parties.
- Duplicate receipt or audience models must not be reintroduced downstream.
- The remaining tax-receipt-to-Direct-Mail runtime seam should converge on a
  fully neutral dispatch hook without changing receipt business ownership.

## ADR-0002: Use A Versioned Neutral Identity-Lock Key Protocol

- Status: Accepted
- Date: 2026-08-12
- Scope: Public identity serialization compatibility
- Supersedes: The app-prefixed Redis key namespace

### Context

Non Profit can coexist with other identity engines that create or reuse the
same Contact, Customer, Member, and Donor graph. An app-prefixed Redis key lets
two engines process the same normalized identity concurrently even though both
individually claim transaction-scoped serialization.

### Decision

Derive ephemeral lock keys as
`identity-lock:v1:{sha256(normalized_type + "\n" + normalized_value)}`. The
normalization and key format are a public interoperability protocol: compatible
engines must produce the same key and contend through Redis. Raw identity values
remain absent from the key. Any format change increments the protocol version
and ships as a coordinated release. Normalized public person-email work uses
semantic type `Contact Email`, matching the Frappe identity row rather than a
business role such as Individual, Member, or Donor. Compatible twins also use
one neutral request-local registry, prepend cleanup callbacks, rearm rollback
cleanup during `before_commit`, guard the after-commit callback phase, and keep
request/job terminal cleanup as the final safety net.

### Alternatives Considered

- Keep the `non_profit` prefix: rejected because it serializes only this app,
  not the shared identity graph.
- Acquire every known app-specific lock: rejected because it couples this public
  app to private implementations and becomes unsafe as engines are added.

### Consequences

- One lock acquisition excludes compatible sibling identity work bench-wide.
- Nested Non Profit to provider calls are reentrant instead of trying to acquire
  the same Redis lock through two app-local registries.
- The rollout needs no persisted-data migration because keys expire after their
  bounded lease.
- Cross-engine parity must derive keys through both implementations and prove
  live mutual exclusion, not compare a test-built expected key with itself.

## ADR-0003: Derive The Receipt Regime From The Company Country

- Status: Accepted
- Date: 2026-08-19
- Scope: Donation Tax Receipt layout and currency
- Supersedes: The CHF-only, single-format receipt contract

### Context

`Donation Tax Receipt` was Swiss by construction: the currency was the constant
`RECEIPT_CURRENCY = "CHF"`, a Company whose default currency was not CHF was
rejected outright, and one `Spendenbescheinigung` Print Format was the only
layout. A German deployment needs EUR amounts and a `Zuwendungsbestätigung`,
which is a regulated form under `§ 50 EStDV` — the heading naming `§ 10b EStG`
and `§ 5 Abs. 1 Nr. 9 KStG`, the amount in figures and in words, the
Freistellungsbescheid of the Finanzamt, and the `§ 10b Abs. 4 EStG` liability
notice. None of that is optional, and none of it belongs on a Swiss receipt.

### Decision

Derive both the currency and the layout from the issuing **Company**: currency
from its `default_currency`, layout from its `country` through the
`RECEIPT_JURISDICTIONS` map, defaulting to the Swiss format. Ship the German
form as a **second Print Format**, not as conditionals inside the Swiss one.

### Alternatives Considered

- A `Non Profit Settings` field selecting the receipt regime: rejected as a
  second source of truth for something the Company country already states, and
  as one more switch that can be left on the wrong value — a mis-set switch here
  issues receipts under the wrong tax law.
- One format with `{% if country == "Germany" %}` blocks: rejected because the
  two forms share almost no required content, and a conditional receipt is a
  receipt that can silently render under the wrong law.
- Keeping CHF-only and forking the app per country: rejected; the domain
  substrate is meant to be jurisdiction-neutral (see ADR-0001).

### Consequences

- Existing Swiss sites are unchanged: an unlisted country keeps the
  `Spendenbescheinigung`, and a CHF Company keeps issuing CHF.
- Adding a jurisdiction means adding a Print Format plus one `RECEIPT_JURISDICTIONS`
  entry, not editing the Swiss format.
- The German notice text is operator data (`de_tax_exemption_notice`), because
  the Freistellungsbescheid is per-organisation and must be quoted verbatim.
- Tests must assert both directions — that the German format carries the
  required references and that the Swiss one still carries none of them.

## ADR-0004: Treat Misdirected Receipts As A Data Problem, With A PDF Password As Backstop

- Status: Accepted
- Date: 2026-08-19
- Scope: Donation Tax Receipt email delivery
- Supersedes: None

### Context

Receipts have reached the wrong inbox. A Bescheinigung names a donor and an
amount, so a misdelivery is a real disclosure. The reflex mitigation the sector
reaches for is a password on the PDF, but the underlying cause in every observed
case was master data: a donor with no email, a typo, two donors sharing one
inbox, or a Donor form showing one address while the receipt resolves to another
through the contact/customer chain.

### Decision

Ship both, and rank them. The `Donation Receipt Email Check` report is the
primary control: it lists the donors whose receipt would misfire *before* the
annual batch goes out, reporting on the address `get_donor_email` actually
resolves rather than the one displayed on the form. Optional PDF password
protection (`protect_receipt_pdf`) is the backstop, defaulting to **off**.

### Alternatives Considered

- Password protection alone: rejected as treating the symptom; a protected
  receipt in a stranger's inbox is still a misdelivery, and the donor still does
  not get theirs.
- A generated password communicated out of band: rejected because it needs a
  second channel the organisation does not have for every donor. The password is
  therefore a detail the donor already knows and the organisation already stores
  — postal code, or Donor ID.
- Encrypting the mail itself: rejected as out of scope for this app; it needs
  per-donor key material that does not exist here.

### Consequences

- The documentation must say plainly that this is *access protection, not
  encryption in transit* — the mail still travels as ordinary SMTP and
  Frappe's `get_pdf` uses pypdf's default cipher. Overstating it would be worse
  than not shipping it.
- With protection on and the Postal Code source, a donor with no postal code
  makes the send **refuse**; silently sending unprotected would defeat the
  setting the operator switched on.
- The report is the thing to run before an annual batch; that belongs in
  `HOW_TO.md`, not only here.

## References

- [Technical documentation](DOCUMENTATION.md)
- [BENCH-ADR-0004 postal ownership allocation](https://github.com/Benema3000/frappe_docker/blob/main/development/ARCHITECTURE_DECISIONS.md#bench-adr-0004-centralize-postal-dispatch-and-separate-carrier-mechanisms)
- [Historical recurring donations plan](https://github.com/Benema3000/frappe_docker/blob/main/development/RECURRING_DONATIONS_PLAN_2026-08-07.md)
