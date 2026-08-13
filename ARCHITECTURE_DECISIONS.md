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

## References

- [Technical documentation](DOCUMENTATION.md)
- [BENCH-ADR-0004 postal ownership allocation](https://github.com/Benema3000/frappe_docker/blob/main/development/ARCHITECTURE_DECISIONS.md#bench-adr-0004-centralize-postal-dispatch-and-separate-carrier-mechanisms)
- [Historical recurring donations plan](https://github.com/Benema3000/frappe_docker/blob/main/development/RECURRING_DONATIONS_PLAN_2026-08-07.md)
