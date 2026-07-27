# Party Model Refactor Plan

Status: Non-authoritative proposal. This document records a candidate
architecture, open decisions, migration gates, and a possible implementation
sequence. It does not change the current requirements, data model, dependencies,
or behavior. `REQUIREMENTS.md`, `DOCUMENTATION.md`, `HOW_TO.md`, and the code
remain authoritative until an accepted implementation change updates them
together.

No phase in this proposal is activated merely because this file is committed.
Activation requires an approved requirement change with stable requirement IDs,
coordinated changes in every affected app, a release/version decision, and a
successful per-site preflight. Until then, terms such as "target", "proposed",
and "recommended" describe design direction only.

## 1. Objective

Establish one consistent identity model for members, donors, volunteers,
households, customers, suppliers, contacts, and addresses without replacing
ERPNext's accounting party infrastructure.

The target should ensure that:

- One natural person has at most one active Person Customer (ERPNext
  `customer_type = "Individual"`) for a selected canonical Person Contact. For
  organizations with verified legal identity evidence, the system prevents more
  than one active legal-organization identity for that evidence. Multiple active
  operating Customer accounts may intentionally project that one legal entity;
  organizations without verified evidence remain subject to duplicate review
  rather than an unprovable uniqueness claim.
- Member, Donor, and Volunteer are roles, not competing identity records.
- A person who is both a Member and Donor reuses the same canonical Contact and,
  once financially relevant, the same Individual Customer.
- A Person Contact is the canonical person identity; Contacts also represent
  non-person communication endpoints when explicitly classified that way.
- Customer is an individual's optional receivable/accounting projection.
- Customer is the operating organization anchor for established Member, Donor,
  or other receivable-side NPO roles, even before the first financial
  transaction; NPO Organization carries shared legal identity across projections.
- Supplier remains the payable/accounting representation.
- A payable-only organization may remain Supplier-only; it must not receive a
  Customer solely to satisfy this identity proposal.
- Household groups people rather than Member or Donor role records.
- Household may receive one optional Customer projection when it becomes a joint
  payer, family Membership account, or explicitly recognized joint Donor.
- Existing submitted accounting history remains valid throughout migration.

## Proposed Architecture Direction

The following points are the recommended direction, not activated requirements:

1. A Contact explicitly classified as `Person` is the canonical identity for a
   natural person. A generic mailbox, department, or other communication
   endpoint remains a Contact but cannot anchor person identity.
2. An Individual Customer is created only when that person becomes financially
   relevant. Creating a Member, prospective Donor, or Volunteer alone does not
   require one.
3. An organization has a base-owned `NPO Organization` identity and is
   represented in ERPNext by a Customer whose `customer_type` is `Company` or
   `Partnership` as soon as it becomes an established Member, Donor, or other
   receivable-side NPO party. A Customer may therefore exist before any invoice,
   Donation, or payment. A payable-only organization may remain Supplier-only;
   both accounting projections link the same NPO Organization when present.
4. Contacts linked to an organization Customer are its representatives or
   communication endpoints; they are not the organization identity. Operational
   Customer hierarchy is also not, by itself, proof of shared legal identity.
5. The current deployment assumption is that Ilanga is not in production. That
   assumption must be proved independently on every deployed site before its
   shared-couple Customer model is replaced; otherwise the migration fallback in
   this plan is mandatory.
6. The current deployment assumption is that Household is not in production.
   No data may be reset or discarded on that assumption alone. Every deployed
   site must pass the Household preflight, or use the conversion path in this
   plan.
7. Volunteer is believed to be unused and may be redesigned around Person
   Contact only after the same per-site preflight confirms that assumption.
8. The product must support controlled identity consolidation and identity
   splitting. Household separation is a dated relationship change, not an
   identity split.
9. Customer and Supplier remain separate ERPNext accounting masters when one
   legal entity has both roles.
10. Family Membership is an explicit Household-scoped Membership with covered
    Members, one payer scope, one matching billing Customer, and one joint ask
    addressed to the Household. Payer scope may be Household or Covered Member.
11. `non_profit` keeps ERPNext as its only required app dependency. Good
    Connector remains optional for enhanced matching, duplicate review, and bank
    integration; no hard identity invariant depends on it.
12. `non_profit` is jurisdiction-neutral. It owns selectable jurisdiction fields,
    immutable qualification facts, accounting/claim integrity, correction lineage,
    and versioned provider interfaces. Jurisdiction-specific entitlement, legal
    wording, numbering, templates, identifiers, currency/language defaults, and
    presentation policy belong to a presentation app. V1 implements only
    Switzerland through `good_npo`; selecting a jurisdiction without a provider
    blocks receipt issue/correction but not ordinary accounting.

## Proposal Authority And Traceability

This file is an RFC-style design input, not a fifth source of current
requirements. Acceptance and activation are separate events:

1. **Proposal acceptance** approves the direction and resolves the decision
   gates, but changes no runtime behavior.
2. **Requirement activation** adds or changes stable requirement IDs in each
   affected app. The requirement must identify its target release and migration
   gate.
3. **Implementation activation** occurs only after schema, backfill,
   remediation, tests, documentation, dependency order, and version bumps ship
   together.
4. **Per-site enforcement activation** occurs only after that site's persisted
   migration run reports zero blocking issues. Installing code must not
   implicitly switch a site from compatibility mode to strict enforcement.

Current contracts remain in force until their activated replacements land. In
particular, Member remains the current Membership identity, Contact links remain
Dynamic-Link based, Good Connector remains optional for `non_profit`, and the
current Household and Donation accounting models remain authoritative.

Activating legal receipt issuance requires a coordinated jurisdiction provider.
Base `non_profit` may activate identity/accounting without one, but cannot submit,
correct, render, or send legal Donation Receipts. Switzerland activation requires
compatible `good_npo` policy/template and Good Connector transport capabilities
only when Swiss QR/QRR features are enabled.

## 2. Vocabulary

| Concept | Meaning | Proposed system record |
|---|---|---|
| Person | A natural person | Contact with identity kind `Person` |
| Generic communication endpoint | Shared mailbox, department, office line, or unnamed endpoint | Contact with identity kind `Generic Endpoint`; never a person identity anchor |
| Organization | Company, association, foundation, NGO, public body, or partnership | NPO Organization identity with Customer for established receivable/NPO roles, Supplier for payable roles, or both when needed |
| Receivable party | A person, organization, or Household from whom money is received or invoiced | Customer |
| Payable party | A person or organization that is paid | Supplier |
| NPO role | A relationship held by a person or organization | Member, Donor, or Volunteer |
| Receipt jurisdiction | Selected legal regime for one Donation Receipt; selectable on a draft and immutable after issue | Country code plus snapshotted provider/policy version on Donation Receipt |
| Receipt policy provider | Jurisdiction-owned decision service for legal entitlement, recipient, issuable amount, document kind, numbering, rendering, and notification | Versioned app hook; Switzerland V1 is provided by good_npo |
| Receipt qualification facts | Jurisdiction-neutral evidence supplied to the policy provider | Submitted allocation, retained cash, recognized amount, dates, recipient candidate, and prior corrections |
| Role activity | A dated or financial event under a role | Membership or Donation |
| Household | A dated social, mailing, and optional joint financial unit of people | Household with Contact-based person rows and optional Customer projection |
| Communication point | Email, telephone, or named representative | Contact |
| Location | Personal, office, postal, shipping, or billing address | Address |

ERPNext's coarse legal-nature classifications remain:

- Customer: Individual, Company, Partnership
- Supplier: Individual, Company, Partnership

These are Select values on Customer and Supplier, not separate external-party
DocTypes. ERPNext `Company` is a different DocType representing an organization
whose books the site keeps, normally our own legal entity. Never create an
ERPNext Company to represent an external member, donor, partner, Customer, or
Supplier.

More specific organization forms such as association, foundation, charity, or
public body should use a separate legal-form field. Member, Donor, and Volunteer
must not become Customer Type values because one Customer may hold several roles.

Before an organization receives an established receivable-side NPO role,
ERPNext Lead or Prospect may be used when a cultivation pipeline is required.
Once it receives a Member, Donor, or comparable role, Customer becomes that
role's organization anchor whether or not a financial transaction exists.
Supplier remains sufficient for a payable-only relationship.

## 3. Current Model

```text
Member ------> Customer ------> Contact / Address
  |
  +----------> Membership

Donor -------> Customer (optional)
  |
  +----------> Donation

Volunteer ---> Contact through Dynamic Link and copied email/name

Household
  +----------> Household Member ---> Member OR Donor

Supplier ----> Contact / Address
```

Current accounting is asymmetric:

- Membership subscriptions and invoices use `Member.customer` and post against
  Customer.
- Donation Payment Entries post directly against Donor as a custom receivable
  Party Type.
- Member is also installed as a receivable Party Type, although current
  membership billing uses Customer.
- Customer and Supplier correctly remain separate ERPNext accounting masters.

## 4. Problems To Resolve

### 4.1 Duplicate identity risk

The current schema does not prevent two Individual Customers from representing
the same Contact. Role-creation helpers attempt reuse, but the relationship is
not a durable data contract.

### 4.2 Roles can create parallel identities

Member, Donor, and Volunteer repeat names, email addresses, or customer links.
The same person may therefore be represented differently in each role.

### 4.3 Customer links are not consistently unique

The database currently allows multiple Member or Donor records to point to one
Customer and does not give Individual roles a direct canonical Contact field.
The target uniqueness rule depends on subject type: Individual roles are unique
by canonical Contact, while Organization roles are unique by organization
Customer. Neither rule is currently a schema-level invariant.

### 4.4 Household contains roles instead of people

`Household Member` currently points to Member or Donor. This causes several
problems:

- The same person can appear twice, once as Member and once as Donor.
- Those two role records can theoretically resolve to different households.
- A spouse, child, or other person without an NPO role cannot be represented.
- Volunteer-only people cannot be represented.
- Organization Members and Donors can be placed in a person-oriented Household.

### 4.5 Household state is duplicated

`Member.household` and `Donor.household` are derived from Household rows, while
`Customer.household` is independently writable. These paths can disagree.

### 4.6 Household membership has no explicit financial meaning

`Membership.is_household_membership` is inferred from household presence, but it
does not currently select a payer, consolidate invoices, or define who is
covered. Living in a Household must not automatically imply a household-level
membership contract.

### 4.7 Customer and Supplier overlap is not documented clearly

One legal entity may be both receivable and payable. ERPNext deliberately keeps
a Customer and Supplier record and links them through Party Link. This is not a
duplicate Customer and should not be collapsed into one accounting record.

## 5. Recommended Target Model

```text
INDIVIDUAL

Contact
  +--> identity_kind = Person
  +--> Member role (optional)
  +--> Donor role (optional)
  +--> Volunteer role (optional)
  +--> Household Person rows
  +--> Individual Customer (optional financial projection)
  +--> Individual Supplier (optional payable projection)
  +--> Contact links to organization Customers and Suppliers

ORGANIZATION

NPO Organization
  +--> verified legal keys (optional)
  +--> Customer(s) [customer_type = Company | Partnership]
  |      +--> Member role (optional)
  |      +--> Donor role (optional)
  |      +--> Contacts as representatives
  |      +--> Addresses
  +--> Supplier projection (optional)

SUPPLIER-ONLY ORGANIZATION

Supplier [supplier_type = Company | Partnership]
  +--> NPO Organization
  +--> Contacts as representatives or communication endpoints
  +--> Addresses
  +--> No Customer unless a receivable-side role is established

INDIVIDUAL FINANCIAL PROJECTION

Customer [Individual]
  +--> Canonical Contact
  +--> Contacts
  +--> Addresses

PAYABLE PARTY

Supplier [Individual | Company | Partnership]
  +--> Contacts
  +--> Addresses
  +--> Party Link to Customer when both represent the same legal entity

SOCIAL GROUP

Household
  +--> Household Person[] ---> Contact
  +--> Household Address Link[] ---> Address
  +--> permission-aware parent loader; no reverse Household Dynamic Links
  +--> optional Household Customer financial projection
  +--> optional Household Donor role for explicit joint recognition
  +--> Family Membership with designated billing Customer and joint ask
```

### 5.1 Identity links versus communication links

The target retains direct canonical fields and Frappe Dynamic Links for role and
accounting projections, but they have different meanings. Household is the
explicit privacy exception described in IR-09 and uses parent-owned child links:

- Direct fields such as `Member.contact`, `Donor.contact`,
  `Volunteer.contact`, `Customer.npo_individual_contact`, and
  `Customer.npo_household` are the identity source of truth.
- Contact Dynamic Links remain relationship and Desk-rendering projections.
  They are maintained transactionally from the canonical field for person-role
  records so standard dashboards and address/contact sections continue to work.
- Organization Contact Dynamic Links remain representative or communication
  relationships and do not establish identity.
- A role form resolves its canonical person and personal Address through the
  direct Contact anchor. It must not infer identity by selecting the first
  Dynamic Link.
- Migration records which Dynamic Link was adopted as the canonical projection.
  Changing a canonical Contact removes or retargets only that managed
  projection; unrelated organization or communication links are preserved.

Address ownership follows the represented subject:

- A person's personal Addresses link to the Person Contact.
- An organization's office, billing, and shipping Addresses link to its
  Customer and/or Supplier accounting masters as appropriate.
- A shared Household Address is referenced from a base-owned, dated `Household
  Address Link` child row and, when an accounting projection exists, may also link
  to the Household Customer. It never carries a reverse Address Dynamic Link to
  Household because loading Address would disclose a Household the caller cannot
  read.
- Member, Donor, and Volunteer do not own new Address identity. Legacy
  role-linked Addresses are relinked to the resolved Contact, Customer, or
  Household during remediation before role-only links are retired.
- Creating an Individual Customer or Supplier projection adds the relevant
  Contact and Address Dynamic Links without moving or deleting person-owned
  records.

### 5.2 Customer subject classification

`non_profit` adds `Customer.npo_subject_type` with values `Unclassified`,
`Person`, `Organization`, `Household`, and `Anonymous System`. This is the
authoritative NPO subject classification; ERPNext `customer_type` remains its
standard technical category.

| NPO subject type | ERPNext `customer_type` | Required identity anchor |
|---|---|---|
| Person | Individual | `npo_individual_contact` |
| Organization | Company or Partnership | `npo_organization` |
| Household | Individual | `npo_household` |
| Anonymous System | Individual | unique `npo_system_identity_key = "ANONYMOUS"` |

For Household, ERPNext `Individual` is only the private/non-corporate accounting
compatibility bucket. It does not mean that the Customer represents one person.
NPO code must branch on `npo_subject_type`, not infer Household from
`customer_type`, name, shared address, or email.

The subject identity anchors are mutually exclusive. Household and Anonymous
System Customers have no `npo_individual_contact` or `npo_organization`; an
Anonymous System Customer also has no `npo_household`. At most one active
canonical Customer may link to a Household. Create it only through a dedicated
Household financial-projection service, never generic Customer Quick Entry.

`NPO Organization` is the stable legal-identity grouping, while each linked
Customer remains an operating/receivable projection and the direct anchor used
by Member, Donor, Membership, and MiKi flows. More than one active organization
Customer may link the same NPO Organization only through a reviewed operating-
unit relationship; this is not a duplicate alias. Organization Suppliers link
the same NPO Organization independently, while Party Link continues to connect
specific Customer/Supplier accounting masters where appropriate.

`Customer.npo_managed_by_non_profit` and
`Supplier.npo_managed_by_non_profit` are the explicit scope markers for strict
NPO validation. Creation/projection services set them read-only; backfill sets a
marker only for an accounting master with an NPO role, canonical NPO subject
anchor, Donation/Membership accounting link, or approved migration decision. A
Party Link with one managed endpoint may adopt the other endpoint only through an
explicit reviewed NPO service; merely discovering an existing link never marks
it. A Party Link whose endpoints are both unmarked remains ordinary ERPNext data
outside this model. Linking an existing master to a new NPO role first adopts and
classifies it through the same service. Unrelated ERPNext Customers and Suppliers
remain unmarked and outside these NPO identity invariants. A marker cannot be
cleared while any NPO dependency remains.

`Customer.npo_household` means “this Customer represents the Household.” It must
not reuse the current `Customer.household` field, whose existing meaning is “this
individual Customer belongs to a Household.” The old field is retired only after
its social-membership meaning has moved to Household Person rows.

## 6. Proposed Identity Rules

### IR-01: One Person Customer per canonical Contact

A Person Contact may be linked to many organization Customers whose
`customer_type` is Company or Partnership as a representative, employee, billing
contact, or other contact person. It may be the identity Contact for at most one
Individual Customer.

Do not use email as the unique identity key. Emails can change or be shared.
Use an explicit stable Contact link, with normalized email/name/address only as
matching and duplicate-review evidence.

Implementation candidate:

- Add a nullable Link field on Customer for the NPO individual identity Contact
  (`npo_individual_contact`), owned by `non_profit`. It is non-unique during
  compatibility/backfill phases; the unique database constraint is created only
  during per-site strict activation after duplicates and aliases are resolved.
- Populate it only when `npo_subject_type == "Person"` and
  `customer_type == "Individual"`.
- Require the linked Contact to have `npo_identity_kind = "Person"` once strict
  enforcement is active.
- Keep `customer_primary_contact` as the operational primary Contact; do not use
  that mutable preference as the sole identity constraint.
- Multiple null values remain valid for Organization and Household Customers.
- Archived aliases clear `npo_individual_contact` and point to their active
  canonical Customer through `npo_canonical_customer`; they do not consume the
  unique identity key.

`non_profit` owns every field and validation required for Member, Donor,
Volunteer, Household, Individual Customer/Supplier projection, aliases, and NPO
Party Link invariants. Good Connector may enhance candidate matching and
duplicate review when installed, but required creation and validation paths have
a complete ERPNext-only implementation and never hide behind optional imports.

This rule proves one Customer per selected canonical Contact. It does not by
itself prove one Contact per real person. Duplicate or source-preserved Contacts
remain an identity-review concern and must be consolidated or explicitly marked
as aliases before the stronger real-person claim can be made.

### IR-01B: One Household Customer per Household

A Household receives an optional Customer projection only when an explicit
financial trigger requires a joint accounting party: family Membership ask,
joint Donation/receipt attribution, Sales Invoice, or reviewed joint Bank Account
ownership.

Creation locks Household before lookup/insert and enforces at most one active
Customer with `npo_subject_type = "Household"` and matching `npo_household`.
Household people keep their separate Person Contacts and optional Individual
Customers. A Household Customer's primary Contact is only an operational
correspondence choice and never its identity anchor.

After an issued ask, submitted accounting document, Bank Account, Donation, or
receipt refers to the Household Customer, its subject type and Household link are
immutable. Household separation preserves this historical Customer rather than
repointing it to either resulting Household.

### IR-02: Member identity depends on Member type

Member gains an explicit subject type and identity anchor:

| Member type | Required identity | Customer meaning | Uniqueness |
|---|---|---|---|
| Individual | Contact | Optional financial projection | At most one Member per canonical Contact |
| Organization | Customer with `customer_type` Company or Partnership | Organization identity and financial projection | At most one Member per organization Customer |

The direct `Member.contact` field is authoritative for Individual Members.
Contact-to-Member Dynamic Links remain managed projections for standard Frappe
navigation; they are not an alternate identity source after activation.

`Member.customer` remains available for both types. It is optional for an
Individual Member until a paid Membership, Subscription, invoice, or another
receivable workflow requires it. It is required for an Organization Member.

A Member may have many historical Membership records, but creating another
Membership must reuse the existing Member role for that identity.

MiKi is a stricter organization-only consumer of this generic model for
declaration-eligible memberships. Every Member used by a MiKi campaign or
Declaration must have `subject_type = "Organization"` and exactly one Customer
whose `customer_type` is Company or Partnership. MiKi keeps its canonical chain:

```text
Membership -> Member -> Customer -> MiKi Declaration
```

Generic Contact-only Individual Members, including MiKi's passive individual
membership type, remain valid in `non_profit`, but are not eligible for MiKi
declaration campaigns. Current MiKi declaration validation rejects a Member
without Customer, campaign selection joins through `Member.customer`, and
migration treats multiple Members for one Customer as a conflict. The refactor
must additionally enforce Organization subject type and `Customer.customer_type`
Company/Partnership at both campaign-selection and declaration-validation
boundaries.

MiKi's Customer hierarchy remains unchanged: campaigns target eligible parent
organization Customers, `Customer.parent_organization` retains child
organizations, and child Customers continue to become declaration items. A
child-specific Member/Membership may exist when the child organization needs its
own membership record, but it must not make the child an independent parent
campaign target accidentally.

### IR-03: Donor identity depends on Donor type

Donor follows the same identity split:

| Donor type | Required identity | Customer meaning | Uniqueness |
|---|---|---|---|
| Individual | Contact | Optional until the first financial event | At most one Donor per canonical Contact |
| Organization | Customer with `customer_type` Company or Partnership | Organization identity and financial projection | At most one Donor per organization Customer |
| Household | Household plus Household Customer | Joint recognition and accounting projection | At most one active Household Donor per Household |
| Anonymous System | Controlled Anonymous Customer; no Contact/Household/Organization | System-only accounting and attribution fallback | Exactly one active system Donor with key `ANONYMOUS` |

The direct `Donor.contact` field is authoritative for Individual Donors.
Contact-to-Donor Dynamic Links remain managed projections and may not select a
different person.

An Individual Donor may exist before making a Donation without Customer. The
first financial event must resolve or create one canonical Individual Customer
and bind it to the Donor before posting.

Anonymous Donations use one controlled Customer and one controlled Donor with
`subject_type = "Anonymous System"` and unique system identity key `ANONYMOUS`.
Only a restricted idempotent setup/service may create or resolve them. They have
no Contact, Household, organization, communication endpoint, or receipt
recipient; identified people are never merged or reassigned into them. Choosing
anonymous is explicit and is not an ambiguity fallback when person matching
fails. These records are excluded from normal Contact uniqueness but included in
system-key uniqueness and accounting preflight.

Anonymous System Customer/Donor are excluded from normal Link selectors and
commercial creation paths. Server guards reject Sales/Purchase Orders, ordinary
Sales Invoices, Subscriptions, Memberships/Asks, unrelated Payment Entries,
shares, and portal-user links. They are permitted only on the explicit anonymous
Donation service and its purpose-marked invoice, payment, Credit Note/refund, and
receipt-correction paths; anonymous Donations never issue a recipient receipt.
Any anonymous unallocated excess remains source-bound `Excess Pending`: it may be
accepted only as an increase of that same anonymous Economic Receipt or refunded
to source. It can never become Released/general anonymous Customer credit or be
reconciled to another anonymous Donation, because the pooled Customer is not
evidence that two receipts share one payer.

A Household Donor uses a dedicated `subject_household` field; it does not reuse
the current derived `Donor.household` field. Its Customer must have
`npo_subject_type = "Household"` and reference the same Household. Create this
role only when joint giving or joint receipt recognition is explicitly selected;
a shared IBAN alone is not sufficient legal evidence for receipt entitlement.

### IR-04: Financial projections are created at explicit triggers

Creating an Individual Member, prospective Donor, or Volunteer does not create a
Customer. The initial proposed triggers are:

- First Donation
- Paid Individual or Organization Membership or Subscription
- Issuing a family Membership joint ask
- Membership invoice
- Sales Invoice or another receivable transaction

Every trigger dispatches by the represented subject. Person activity reuses the
Person Customer for canonical Contact, Organization activity uses the selected
organization Customer, and Household payer activity locks Household and reuses
its Household Customer. Ambiguous or inconsistent identity matches go to review.

### IR-05: Volunteer is person-oriented

Volunteer links explicitly to one canonical Contact and remains a person role.
It does not require a Customer unless the person separately enters a receivable
relationship.

If corporate volunteering is required, add an optional organization Customer to
the Volunteer or volunteer engagement record. Do not represent the company
itself as a person Volunteer.

If volunteer reimbursements are introduced, use Supplier or Employee according
to the payable business process. Do not create a Customer solely because the
person must be reimbursed.

Volunteer should use a stable series or UUID rather than email as its document
name. Email and display name are resolved from Contact rather than serving as
identity keys. The initial model allows at most one Volunteer per canonical
Contact. Future assignments, types, or periods belong in a Volunteer Engagement
rather than duplicate Volunteer identities.

The Contact must be classified as `Person`. Existing email-named Volunteers are
renamed only through a controlled migration that preserves incoming links and
external references; changing email never renames the target Volunteer.

### IR-06: Customer and Supplier remain separate

When one legal entity has both roles:

```text
Customer <--- Party Link ---> Supplier
```

Identity matching should help create or select the corresponding record, but
Sales and Purchase transactions must continue to use ERPNext's standard party
masters.

A Supplier-only person or organization is valid. Pairing to Customer occurs
only when the same legal entity acquires a receivable-side relationship; it is
not a prerequisite for Supplier creation.

Party Link alone is not accepted as proof of a one-to-one identity. Goodvantage
validation applies only when at least one endpoint is already NPO-managed and the
other is explicitly adopted. It enforces at most one paired Customer per Supplier
and one paired Supplier per Customer within that scope. Ordinary Party Links
between two unmarked ERPNext masters remain unchanged. Individual NPO pairs must resolve to the same canonical
Contact. Organization pairs require compatible party types and matching legal
identity through the same NPO Organization; explicit staff approval establishes
that link when no verified key is available. Where one legal entity has several
operating Customers, each Party Link still names the specific accounting pair
and does not imply that the Supplier links every Customer automatically.

Adoption requires a service-owned `NPO Party Link Approval`, distinct from NPO
Organization Projection Approval. It stores the normalized Customer/Supplier pair,
immutable unique pair key, identity evidence, approver/date, `Active` or `Revoked`
status, reason, and immutable action history. At most one active approval exists
per pair; retries reuse it. Both endpoints must independently satisfy their Person
or NPO Organization projection rules before this approval can authorize pairing.

NPO-managed Party Links are service-owned after adoption. `on_trash` and unlink
guards reject direct Desk delete, bulk delete, import, and RPC. A controlled
unlink previews dependent roles/accounting, locks identity control, both endpoints
in sorted order, Party Link, and Party Link Approval, revokes only that pair
approval, records the reason, and clears pairing only when no invariant depends on
it. It never revokes either endpoint's NPO Organization Projection Approval or
clears `npo_organization`; endpoint unadoption is a separate operation. Party
Links whose endpoints are both unmarked retain ordinary core behavior.

### IR-07: Organization Contacts are not organization identities

A Contact attached to an organization is a representative of that Customer or
Supplier. It must not cause the organization and the person's Individual
Customer to be merged.

A linked Contact can be a named person or a generic communication endpoint such
as an office mailbox. In both cases, the organization Customer remains the
organization identity. Per-organization roles such as billing contact,
membership contact, or director must live on an explicit relationship when one
Contact can hold different roles for different organizations; global Contact
fields are not sufficient for that case.

### IR-08: Contact identity kind is explicit

`non_profit` adds `Contact.npo_identity_kind` with values:

- `Person` — a natural person and eligible canonical anchor for Individual
  Customer, Individual Supplier, Member, Donor, Volunteer, and Household Person.
- `Generic Endpoint` — a mailbox, department, unnamed office contact, shared
  telephone endpoint, or similar communication record. It may link to
  organization Customers/Suppliers but cannot anchor person identity.
- `Unclassified` — compatibility value for existing Contacts pending backfill.
  It is not eligible once strict person-identity enforcement is active.

Backfill may classify a Contact automatically as `Person` only from strong
structural evidence, such as an existing Individual role plus a non-generic
name. Email alone is never sufficient. Generic-looking or contradictory rows
enter manual review. Changing `Person` to `Generic Endpoint` is blocked while
active person roles or financial projections refer to the Contact.

Person proof uses `NPO Verified Identity Endpoint`, not mutable Contact Email text
alone. The normal DocType stores Contact, endpoint type, normalized/value
snapshot, Personal/Shared classification, verification method/date, status, and
a nullable unique active key. Verification locks that key and Contact; only one
active Personal endpoint row may claim a normalized email across active Person
Contacts. Shared/Unknown values never receive a Personal active key.

Changing/removing/copying the underlying Contact Email first locks and revokes the
old endpoint row, clears its active key, invalidates outstanding claims/tokens,
and creates a new unverified value; focused writes cannot bypass the service. A
claim token binds endpoint-record ID, Contact, and immutable normalized-value
hash, and consumption rechecks all three plus active uniqueness under lock.
Legitimate endpoint transfer requires staff review and leaves the revoked row as
history.

### IR-09: Direct fields and Dynamic Links cannot disagree

For Individual Member, Donor, Volunteer, Customer, and Supplier records:

- The direct canonical Contact field is authoritative.
- `non_profit` adds `Dynamic Link.npo_identity_projection` and
  `npo_identity_owner_field` so a generated projection can be distinguished from
  an operator-managed representative/communication relationship. These fields
  describe only projection provenance; existing MiKi connection-role metadata
  remains independent.
- A managed Contact Dynamic Link to the role/accounting record is required for
  standard Frappe navigation and rendering.
- A second Contact Dynamic Link may remain only as an explicitly classified
  communication relationship; it cannot be treated as another identity.
- Canonical-link services update the direct field and managed projection in one
  transaction and validate both before save.
- Changing a direct canonical field removes only the prior row marked as that
  field's identity projection. An unmarked or differently classified Dynamic
  Link is never deleted automatically.
- Legacy role-linked Addresses are not deleted until the remediation run proves
  an equivalent Contact/Customer/Household link exists.
- Before core Contact validation runs `deduplicate_dynamic_links()`, an
  upgrade-tested `before_validate` reconciler groups duplicate
  `(link_doctype, link_name)` rows. Compatible NPO projection and MiKi
  relationship-role metadata is merged into one row; conflicting provenance or
  role values block save for review. Managed services never append a duplicate.
  This prevents Frappe's core two-field dedupe from silently dropping custom
  metadata.

For Household, current Household Person and Household Address Link rows are
authoritative. The target model does not persist Contact-to-Household or Address-
to-Household Dynamic Links: generic Contact/Address hydration serializes those
children without checking permission on the linked Household. A permission-aware
Household loader derives current people and shared addresses from the parent-owned
rows only after raw Household access succeeds; ended rows remain history.

### IR-09B: Identity anchors cannot silently retarget history

Canonical identity fields are read-only and service-owned:
`Member.contact/customer`, `Donor.contact/customer/subject_household`,
`Volunteer.contact`, Customer Person/Household/Organization/system anchors, and
Supplier Person/Organization anchors. A controlled correction may retarget an
unused record only after a dependency preview proves there is no Membership,
Donation, invoice, payment, receipt, Household history, portal/source identity,
communication, or submitted/unsubmitted business activity that would be
reattributed; it updates managed projections and writes an audit in one locked
transaction.

For Individual Member/Donor, an initially empty optional Customer field may be
populated once by an approved financial trigger when that Customer is anchored to
the unchanged canonical Contact; this binds a projection and is not identity
retargeting. Once bound or referenced by accounting, it cannot change. For
Organization/Household roles the Customer/Household is the identity anchor and is
frozen as soon as any role dependency exists.

The versioned migration/adoption service may fill a previously absent NPO anchor
on the same existing Customer/Supplier/role from approved deterministic evidence;
that classification does not move documents to another record. After the
persisted adoption decision or strict activation, changing the nonempty anchor is
retargeting and follows the freeze/split rules above.

After any such dependency exists, the anchor is historically immutable. A wrong
identity is resolved through the split/consolidation/Settlement Only/alias
operations, which preserve old document ownership and route only supported future
activity. Validators compare persisted values and reject Desk, import, API, and
focused-write retargeting outside the controlled service. Operational primary or
billing Contacts may still change because they are communication preferences,
not identity anchors.

The one non-destructive organization-anchor exception is the legal-identity
consolidation in IR-10: it retargets only Customer/Supplier `npo_organization`
grouping under all-source locks and approval history, never the accounting master,
role subject, Customer/Supplier Party Link, or submitted voucher party.

### IR-10: Organization canonicality is evidence-bounded

The model does not claim that arbitrary organization names prove legal
identity. `non_profit` owns:

- `NPO Organization`, the stable legal-entity grouping with identity status,
  canonical-alias link, and optional primary Customer; and
- `NPO Organization Verified Key`, a normal DocType containing organization,
  scheme, normalized/display values, verification authority/reference/date,
  operator, lifecycle status (`Active` or `Revoked`), revocation reason and
  actors/dates, and an immutable unique `canonical_key` such
  as `SCHEME:normalized-value`; and
- `NPO Organization Projection Approval`, a service-owned record for each
  Customer/Supplier-to-organization projection with evidence, status
  (`Active`, `Settlement Only`, or `Revoked`), approver/date, and immutable action
  history.

Organization Customers and Suppliers link through `npo_organization`. One NPO
Organization may intentionally have multiple active operating Customers and a
Supplier projection only while each link has an Active Projection Approval;
direct field edits cannot create the relationship. Verified-key uniqueness applies to NPO Organization, not to
each Customer. MiKi parent and child Customers that are proven operating units of
one legal entity may therefore share the same NPO Organization and verified UID
while remaining separate Customers and declaration items. A child with its own
verified UID links another NPO Organization; a blank UID or
`parent_organization` alone never infers either result.

A canonical verified key row is never deleted or recreated under another name.
Revocation tombstones it with evidence; routine creation cannot reuse the value.
Controlled re-verification reactivates the same row. Transfer locks source and
target organizations, changes ownership on that same row while it remains Active,
and appends a `Transferred` immutable NPO Organization Identity Action; Transferred
is an action, not a stranded key status. Projection revocation first enters
Settlement Only when historical/open dependencies require the nonempty
`npo_organization` link: new NPO use is blocked, but exact historical settlement/
correction remains allowed. Revoked is permitted only after a locked zero-
dependency unlink, which clears the projection field and retains approval/action
history.

`Customer.business_uid`, `Customer.legal_form`, or fields exposed by another
installed owner remain preserved source evidence. A format-valid value is not
automatically verified. Installed apps contribute versioned evidence providers;
only an explicitly approved/verified result creates or changes a unique key.
Provider installation, removal, or version change invalidates the provider
manifest and requires re-preflight before strict identity activation can
continue. A focused source-field write calls the evidence service and creates or
updates a review claim; it never changes an existing verified key automatically.
`non_profit` never imports a downstream app or transfers ownership of its fields.
On an already active site, a provider manifest mismatch suspends verified-key
mutation and requires controlled re-verification before Active resumes; it never
silently discards a key.

The registry and evidence interface are jurisdiction-neutral. `non_profit` ships
no Swiss UID normalizer or verifier. For V1, `good_npo` registers the `CH_UID`
policy; MiKi-owned `business_uid` remains source evidence submitted through the
generic interface and cannot create a verified key by itself.

Organizations without a verified UID may still have an NPO Organization and
accounting projections, but name/address similarity produces duplicate-review
candidates, not automatic merge or false uniqueness. Consolidating NPO
Organizations transfers verified keys only under locks and never collapses
intentional operating Customers. Customer/Supplier Party Link identifies a pair
of accounting projections; agreement on NPO Organization is required, but Party
Link itself is not the legal identity registry. Legal form is mutable descriptive
data and never part of a uniqueness key.

NPO Organization consolidation is the sole controlled exception to immutable
nonempty organization projection anchors. It locks source/canonical organizations,
verified keys, every Customer/Supplier projection, approvals, and dependent roles
in global order; transfers key ownership through Identity Actions, supersedes each
old approval with immutable history, and retargets the projection to the canonical
organization without changing any accounting master or voucher party. A
projection with open/correctable history becomes Settlement Only under the
canonical organization; otherwise it may become Active after current validation.
No active projection remains on the Archived Alias, and intentional operating
Customers are never merged.

### IR-11: Archived aliases have explicit lifecycle fields

`non_profit` owns these NPO identity and accounting-master fields:

- `Contact.npo_identity_status`: `Active` or `Archived Alias`.
- `Contact.npo_canonical_contact`: Link to Contact, required only for an archived
  Contact alias. An archived Contact cannot anchor an active role or financial
  projection.
- `Customer.npo_identity_status`: `Active`, `Settlement Only Alias`, or
  `Archived Alias`.
- `Customer.npo_canonical_customer`: Link to Customer, required only for an
  archived Customer alias and forbidden on an active Customer.
- `Supplier.npo_identity_status`: `Active`, `Settlement Only Alias`, or
  `Archived Alias`.
- `Supplier.npo_canonical_supplier`: Link to Supplier under the same rule.

non_profit owns equivalent role fields:

- `Member.identity_status` / `Member.canonical_member` and
  `Donor.identity_status` / `Donor.canonical_donor`; status supports Settlement
  Only Alias while persisted legacy Party Type accounting still depends on that
  exact role.
- `Volunteer.identity_status` and `Volunteer.canonical_volunteer`.
- `NPO Organization.identity_status` and `canonical_organization`; a genuine
  legal-identity consolidation transfers verified keys to the canonical
  organization without merging intentional operating Customer accounts.

Archiving is a controlled operation, not an ordinary field edit. It requires a
dependency preview, locks alias then canonical records in deterministic
doctype/name order, clears unique canonical Contact keys from the alias, records
the canonical link and reason, and writes an immutable audit result. Verified
organization keys move only through NPO Organization consolidation. Archiving a
Contact first
retargets or resolves every active canonical role/accounting field and managed
projection; unresolved portal User, source-ID, or communication ownership is a
blocking conflict. Archived aliases retain the minimum historical display and
accounting links required by submitted records.

An accounting master or legacy Member/Donor accounting party with open items or
documents that may still require
cancellation, amendment, reversal, or exact-party settlement cannot become a
fully disabled Archived Alias. It first becomes Settlement Only Alias: normal
selectors and all new commercial/role activity exclude it, but tightly scoped
services may settle or correct only pre-archive documents against that exact
historical party. Creating unrelated invoices, Donations, Memberships, or
payments remains blocked. Once no open/correctable dependency remains, the
operation may set ERPNext `disabled` where available and finalize Archived Alias.
Reactivate is allowed only after the same uniqueness and dependency checks pass.

Native rename/merge is fenced for every protected-lifecycle registry entry. This
explicitly includes NPO-managed Contact, Customer, Supplier, Member, Donor,
Volunteer, NPO Organization, Household, Membership, NPO-managed Subscription,
Membership Ask, Donation,
Donation Receipt, Payment Intent, Economic Receipt/Source, Accounting Event,
verified endpoint/key, controls/configuration/audit/outbox records, and standard
Sales Invoice, Payment Entry, Journal Entry, Bank Account, Contact, or Address
records when the persisted or requested record is NPO-managed/NPO-purpose. The
registry default is deny; any allowed zero-dependency technical rename names its
operation and audit policy. A v16 `extend_doctype_class` guard on every protected
DocType overrides the public document `rename` method and rejects caller-supplied
`validate_rename = false`;
the server-side `before_rename`/merge guard then rejects `rename_doc(...,
merge=True)`, Desk Rename/Merge, import, and direct RPC unless the controlled
consolidation/split service supplies a locked, validated operation ID. Protected
code never calls `frappe.rename_doc(..., validate=False)`. Non-merge technical
renames such as the Volunteer naming migration use the same operation context
and validated path. This prevents core from rewriting submitted links and
deleting a source outside the dependency preview.

Frappe `Document.discard()` is also explicitly fenced because it bypasses normal
cancel/validate hooks. `before_discard` rejects every no-delete, retention-managed,
parent-only, shared-resource, or dependency-protected registry entry, including
fixed activation/config rows, managed identities/roles/Party Links, Donations
with live Intent/Economic Receipt/history, and NPO-purpose Sales Invoice/Payment
Entry/Journal Entry, unless the corresponding controlled retention/cancel/
reversal/unlink operation owns the request.
That hook alone is insufficient: generic save endpoints preserve a caller-
supplied `_action = "discard"`, which skips transition and lifecycle checks
without calling `Document.discard()`. REST create, `frappe.client.insert`, and
`insert_many` also preserve it and enter `insert()` directly. The v16
`extend_doctype_class` guard on every protected parent, voucher, and sensitive
child DocType therefore rejects `_action = "discard"` at the start of both
`insert` and `_save`; no legitimate new-document path uses discard. The canonical
`discard()` method does not use either path and continues through
`before_discard`. `on_discard` verifies the expected audit transition. Import,
REST v1/v2 create/update, `frappe.client.insert`/`insert_many`/`save`, Desk save,
and document-method RPC tests prove that discard cannot be used as a generic
write/delete shortcut.

Delete/trash and standalone child writes have their own boundary. A versioned
protected-lifecycle registry, included in the installed-capability manifest,
classifies every new or extended identity/accounting DocType as one of:

- **No delete:** activation/configuration rows, migration runs/issues/evidence,
  verified identity endpoint/key history, organization Projection Approval and
  Identity Action, NPO Party Link Approval, NPO Protected Change Audit, NPO Ledger
  Repost Run, alias/consolidation/split audit,
  Economic Receipt source and observation records, Accounting Events, Refund
  Instructions/Sources, Credit Applications, Membership Ask Economic Receipts/
  Sources/Observation Locks, allocation claims, and receipt correction history.
  Controller `before_discard` and `on_trash` guards reject
  Desk, import, bulk, REST, document RPC, and direct `frappe.delete_doc` unless a
  named recovery operation is explicitly allowed by that record type; immutable
  evidence has no such operation.
- **Retention-managed delete:** expired Identity Claims and delivered/dead-letter
  Accounting Outbox, terminal Deferred Work, or Protected Diagnostic payloads may
  be minimized only by their retention service
  after the configured period, under a locked operation ID. `before_discard` and
  `on_trash` block ordinary lifecycle calls. The Outbox/Work row and its uniquely
  constrained event/work key, purpose/source fingerprint, terminal disposition,
  and timestamps are a permanent non-PII tombstone; only payload/error/lease
  detail is erased, so replay can never recreate and resend the same action. A
  dead-letter is eligible only after an operator marks it terminal rather than
  retryable.

Immutable/no-delete means the audit row and action history survive, not that raw
PII is retained forever. Verified endpoint snapshots, Protected Change Audit raw
before/after values, privacy evidence, and diagnostics store sensitive payload in
envelopes encrypted with purpose/subject-scoped data keys. After legal retention
and absent legal hold, a controlled minimization operation clears active unique
keys, detaches the subject where permitted, cryptographically erases the payload
key, and retains only non-reversible fingerprint, record/action type, dates,
authority, and erasure audit. Active identity/financial evidence cannot be erased;
revoked endpoint uniqueness and alias safety are rechecked under lock first. This
is payload minimization, never row deletion or history rewrite.

Selective erasure requires a versioned deployment-owned
`protected_payload_key_provider`, not Frappe's restorable site encryption key.
Every provider derives immutable `(deployment, site UUID, incarnation)` identity
from a site-scoped workload credential; caller-supplied site identity is only an
assertion and must match. Each envelope has an independent globally unique DEK/key
ID bound by provider policy and AEAD associated data to that site identity,
envelope UUID, domain, purpose, opaque subject-set fingerprint, algorithm/version,
and ciphertext fingerprint. Site rename/clone, credential substitution, cross-site
key/context/ciphertext swap, and recreation of a destroyed key ID fail without
existence disclosure. A controlled hostname/site-name change retains the same site
UUID/incarnation and provider context. Physical clone/copy into a new site is
prohibited once any protected envelope/history/hold/journal state exists; disaster
recovery is a same-UUID/incarnation restore through the deployment shim, and test/
successor sites use a redacted non-PII export with new keys. A proven never-
activated, no-protected-history site may initialize independently; namespace reset
is never an escape.

Unwrapped DEKs are non-exportable handles or operation-local memory only and are
never serialized to DB/files/Redis/RQ/logs or persistent/process caches. Reads use
bounded provider generations/leases. Provider-enforced idempotent CAS hold/release
and key lifecycle transitions ensure destroy rejects new leases, verifies the
latest hold version, drains/revokes existing leases, and returns only when no
system process can release new plaintext. A payload spanning subjects is split
where possible or remains held until every subject/purpose is erasable. Signing/
KEK rotation, outage, lost-response, duplicate/reordered-call, and partial-state
recovery are defined; strict activation/read/destroy fails closed on unavailable or
stale provider state.

The deployment layer maintains a signed monotonically sequenced erasure journal
outside ordinary DB/files/site-config backups with idempotent `Prepared -> Key
Destroyed -> Blob Purged -> Committed` transitions. Destroy requires the Prepared
event and current hold version; recovery resumes every partial transition. Restore
reconciles epoch plus external key/hold/journal state even when model epoch still
matches, before web/workers/callbacks start. Files first enter non-web quarantine,
erased locators are purged, and only then may retained files be published. Backup
retention/expiration follows key-destruction obligations.

That journal covers controlled plaintext anonymization/deletion/minimization too,
not only envelopes and Files. Before the local privacy mutation commits, it writes
a versioned encrypted replay instruction for affected database row/field versions,
relationship removals/tombstones, User/session/API-credential revocation, and blob
locators, then marks every older backup generation `Redaction Replay Required`.
Permanent metadata uses only opaque keyed locators; exact DocType/name/field/
replacement operations are encrypted under the restore-cleanup key. Staged restore
replays every operation after the backup's journal head, revalidates schema and
row versions, and proves no subject/link/credential plaintext remains before
promotion. An unknown schema, irreconcilable row, or unavailable replay instruction
permanently invalidates that backup generation. Replay detail survives until all
affected generations have deletion/expiry attestations.

Provider audit/journal records are protected artifacts. Permanent records contain
only site-scoped opaque IDs and keyed non-cross-site-correlatable fingerprints,
never raw subjects, filenames, URLs/paths, request payloads, plaintext keys, or
globally reusable content hashes. Exact purge locators are encrypted under a
separate restore-cleanup operational key, available only to quarantine cleanup and
destroyed after every affected backup generation expires. Provider storage,
access, exports, logs, and retention inherit the strongest source domain.

Strict activation also requires a deployment-owned
`party_model_backup_restore_shim`; Frappe has no safe post-restore hook before live
public files are extracted. Every sanctioned scheduled/manual backup, restore, and
site start runs through this shim. Core `scheduled_backup` and direct live-site
`bench backup/restore` entry points are disabled/rejected in the managed deployment
unless invoked by the shim's operation credential; direct host filesystem/SQL use
remains explicitly trusted-host scope.

Backup registers an immutable external generation manifest and completion/deletion
attestation containing only opaque backup ID, site UUID/incarnation, epoch/
capability hash, key/hold/journal generations, keyed archive fingerprints, expiry,
and disposition. The manifest state is `Preparing`, `Capturing`, `Completed`,
`Expired`, or `Deleted`. Preparing acquires a site-wide protected-writer/File/
callback/outbox barrier or a storage-level consistent snapshot and binds one DB
snapshot/binlog coordinate, immutable file generation, configuration fingerprint,
provider key/hold/journal heads, and outbox/work head. Provider/file heads are read
before and after capture; drift aborts unless an explicit ordered replay delta is
attached. Completed requires source-graph and DB-to-blob reconciliation, not only
archive hashing; unknown/orphan blobs stay quarantined.

Restore creates an isolated database/site/files root with no web,
static-file, worker, scheduler, or callback route, invokes core restore only there,
reconciles provider/manifest/hold/erasure state, purges erased encrypted locators,
and verifies complete retained/purged fingerprints. Only then may a signed
promotion receipt atomically replace the live generation. The deployment start
shim refuses backend workers and frontend/static serving until current external
state and promotion receipt match. Cleanup locator keys survive until every
manifest generation containing the path has a deletion/expiry attestation.

The external coordinator also owns one monotonically increasing runtime generation
and fencing token for each site UUID/incarnation. Every deployment holds a bounded
renewable exclusive generation lease. Disaster-recovery promotion requires the
prior generation to surrender or be externally revoked and its leases to drain/
expire, then CAS-advances the generation, issues a new workload credential, and
revokes prior provider/key, queue/callback/outbox, and frontend/static-route
leases. Every protected request/read/write/key operation/job/callback validates its
generation lease; external delivery and final DB writes recheck uncached
immediately before effect/commit. The edge/static serving path validates the same
generation. A partitioned/stale generation cannot renew, regain a route, or resume
after promotion, even without process restart.

The successor/test alternative is a named, authorized, versioned default-deny
redaction export, never a site clone. Its field/artifact allowlist and schema hash
exclude raw/linkable subject identifiers, free text, Files/filenames,
communications, audit/diagnostic/import/job rows, credentials, ciphertext,
key/provider identifiers, and reversible or cross-site-correlatable hashes.
Included facts are synthetic or satisfy an approved aggregation threshold. Unknown
schema/content aborts; adversarial content scanning and a signed non-PII attestation
precede release. The target starts with a new UUID/incarnation, credentials, and
independent keys.
- **Parent-only mutation:** `Contact Email`, `Dynamic Link`, `Household Person`,
  `Household Address Link`, `Membership Covered Member`, `Subscription Plan
  Detail` under an NPO-managed Subscription, Membership Ask allocation/
  disposition children, Donation Receipt allocation children, and `Sales Invoice
  Item`, `Sales Taxes and Charges`, `Sales Invoice Advance`, `Payment Entry
  Reference`, `Payment Entry Deduction`, `Advance Taxes and Charges`, `Journal
  Entry Account`, or `Process Payment Reconciliation Log Allocations` rows whose
  persisted or requested parent is NPO-managed/NPO-purpose. Their controller
  mixin rejects standalone `insert` and `_save`, while `before_discard` and
  `on_trash` reject canonical discard/delete, unless the permitted, locked parent
  service owns a request-local operation sentinel. Both old and requested parent
  identities are checked so retargeting cannot escape the rule. Normal parent
  hydration/save remains supported under that parent context. Because
  `frappe.client.insert_doc/delete_doc` and normal parent save bypass child
  controllers and write child rows directly, every protected parent `insert`/
  `_save` first computes a persisted-versus-requested diff for all registered
  child fields. For identity/relationship children, the parent guard acquires
  control and every requested identity target in the global order before the
  parent, validates every add/change/remove/retarget,
  and records a semantic fingerprint that excludes framework-assigned row names/
  indexes. Mutation-capable lifecycle/app hooks are forbidden from changing these
  protected child relationships. After all `before_insert`/`before_validate`/
  `validate`/`before_save` hooks and framework normalization, parent `db_insert`
  (new documents) or the overridden `update_children` (updates) rechecks the final
  semantic fingerprint immediately before child SQL while the locks remain held;
  drift throws and rolls back the parent write. The unforgeable scoped sentinel
  exists only around the approved `super()` path. NPO-purpose accounting parents
  reject generic child diffs and require their focused service. Financial-owner
  children that reference downstream vouchers are the explicit lock-order
  exception: Ask allocation/disposition and Sales Invoice Advance use control/
  configuration -> Ask -> Economic Receipt/Source -> Sales Invoice -> Payment
  Entries -> child SQL; Process reconciliation allocations use the owner-first
  sanitizer order. The parent guard verifies those locks and final fingerprint but
  never reacquires a voucher before its owner.
  `Process Payment Reconciliation Log Allocations` protection never depends only
  on its parent marker: old and requested Payment Entry/invoice references are
  resolved independently, and either being NPO-owned activates the guard. The
  collector also maintains read-only `npo_contains_protected_allocations` on the
  Process and Log parents for coarse fencing; clearing/omitting that marker cannot
  bypass row-level resolution.
- **Protected scalar mutation:** the registry separately enumerates canonical
  anchors/status, NPO-managed/subject/scope markers, namespace/idempotency keys,
  financial purpose/owner/reversal links, control/configuration state, and every
  other service-owned scalar. Entry guards validate the requested transition and
  store its permitted semantic fingerprint under locks. Cooperative parent
  `db_insert`/`db_update` guards revalidate the final scalar fingerprint after all
  controller/app/Server Script `before_validate`/`validate`/`before_save`/
  `before_submit` hooks and immediately before SQL; a later hook that retargets,
  clears, or forges a scalar rolls the transaction back. Effective scalar field
  registries and final-write MRO are capability-manifest inputs.
- **Shared-resource mutation:** `DocShare` rows whose persisted or requested
  target is Household or Membership use the protected `_save` and
  `before_discard` guards plus the common target-parent locking/recheck protocol
  in section 12; direct canonical/forged discard, retarget, and race paths cannot
  bypass the sharing prohibition.
- **Protected artifacts:** File, Communication/Communication Link, Email Queue,
  Comment, Notification Log, Document Follow, ToDo/assignment, Document Share
  Key, Tag/Tag Link, Version, Deleted Document, Prepared/Auto Email Report, Data
  Import/File/Log, Submission Queue, Integration Request, Access/View/API Request
  Log, Route History, Error Log, RQ/Scheduled Job diagnostic records, email-read
  tracking, `_seen`, `_liked_by`, and privacy request/export rows inherit the
  strongest persisted/requested source domain. Their create/read/copy/retarget/
  send/download/follow/assign/discard/trash/retention policies are part of the same
  registry rather than ordinary owner permission.
- **Controlled document lifecycle:** managed masters and financial documents may
  use only the archive, cancel, return, reversal, or correction service defined
  for their dependency state; ordinary trash is rejected once protected history
  exists.

Core `Deleted Document` is not a reactivation path. Protected records are
normally archived/cancelled rather than physically deleted. For any permitted
deletion of an unused protected draft, a pre-delete service writes the durable
restricted audit first. Core inserts Deleted Document with `db_insert()` and runs
no controller lifecycle hooks, so a cooperative v16 `extend_doctype_class`
override of `DeletedDocument.db_insert` classifies the source, sets service-owned
protection-domain/source fields, and replaces its full JSON snapshot with a non-
PII tombstone **before** calling `super().db_insert()`; `before_insert` is not
relied upon. Preflight migrates/minimizes existing protected
snapshots the same way before users regain access. Permission hooks deny raw
protected Deleted Document rows outside the matching identity/accounting
authority. Overrides for both core `restore` and `bulk_restore`, plus the protected
DocType `insert` guard when `flags.from_restore` is set, reject ordinary restore.
An exceptional pre-activation recovery must use a named locked service, re-run
current uniqueness/reactivation/create validation, and append audit; no public
method accepts its operation sentinel. Core old-log cleanup may remove the
non-authoritative tombstone after retention because the durable protected audit,
not Deleted Document, is the evidence authority.

ERPNext `Transaction Deletion Record` is also an explicit protected surface. Its
worker deletes parents, children, Versions, comments, and communications with
query-builder/`frappe.db.delete`, bypassing every document hook. A cooperative
`extend_doctype_class` guard therefore rejects validation/submission on any
activated or protected-history site when the requested Company/DocTypes could
contain an NPO-managed, NPO-purpose, registry, child, audit, activation, or
accounting row. A proven clean, unactivated site is the only allowed case. The
same guard runs again in `execute_task`, `delete_company_transactions`, and the
parent/child batch-delete helpers before each destructive call, so a tampered
submitted record or direct worker invocation cannot rely on form validation.
Activation inventories queued/running deletion jobs and refuses to fence/activate
until they are cancelled or completed and the data fingerprint is rebuilt. The
Transaction Deletion Record extension/MRO, worker guard version, and protected-
doctype registry hash are capabilities; a missing/stale guard suspends or enters
Recovery Required before writers resume.

ERPNext `Repost Accounting Ledger` and `Repost Payment Ledger` are protected
surfaces because their workers delete/recreate GL, Payment Ledger, and Advance
Payment Ledger rows without normal voucher hooks. A repost range containing an
NPO-purpose voucher requires an immutable `NPO Ledger Repost Run`, accounting
authority, committed donation/membership fence, writer/callback drain, and exact
affected-voucher/source fingerprint. Validation and direct worker entry resolve
and lock every Ask/Membership Subscription cycle/Donation/Refund/Credit Application
owner in deterministic order before vouchers, then invoke core repost under the
operation sentinel.
Afterward the service rebuilds settlement/receipt/fundraising facts and verifies
voucher-to-GL/PLE/advance/claim fingerprints before returning controls to their
prior state. Unknown/range-expanded vouchers, direct worker calls, or partial
failure remain Fenced/Recovery Required. Ordinary repost ranges proven free of
protected vouchers retain core behavior; effective classes/workers are manifest
capabilities.

Core's after-commit `frappe.model.delete_doc.delete_dynamic_links` cleanup may run
for a protected source only as a verified no-op. A rare permitted physical-delete
service locks the source and all artifacts, writes durable audit, rehomes/
minimizes retained artifacts, revokes follows/shares, and proves zero rows for
every core cleanup predicate before deleting the parent. It persists an exact
protected-cleanup permit/work key. The registered `before_job` guard requires that
permit and repeats the zero-row check; any residual row fails closed and routes to
the protected retention service rather than raw deletion/unlink. Artifact creation
also rejects a deleted/cleanup-pending protected source, closing the post-commit
gap. Ordinary archive/cancel schedules no such job.

The registry names the effective controller mixin/hook for every entry and the
activation preflight rejects a missing class, non-cooperative `super()` chain, or
hash mismatch. Direct `db_set`, `db_update`, raw SQL, and `ignore_*` flags remain
trusted-server-only primitives prohibited by lint/code review outside the named
services; no public method accepts an operation sentinel or ignore flag.

### IR-12: Uniqueness is concurrency-safe

- Use database unique indexes for unconditional keys after aliases have cleared
  those keys.
- Where MariaDB cannot express a conditional active-only unique constraint,
  lock the canonical Contact, NPO Organization, or verified-key row
  before lookup/create and recheck under the lock.
- Financial-projection creation locks the Person Contact before querying or
  inserting Customer/Supplier.
- Household financial-projection and Household Donor creation lock Household
  before querying or inserting the Customer/Donor.
- Role creation locks the canonical Contact or organization Customer before
  querying or inserting Member/Donor/Volunteer.
- Household mutation locks affected Person Contacts in sorted name order, then
  every affected Household parent row in sorted order, then Household Person
  rows. The common parent mutex serializes two different Contacts concurrently
  becoming primary/current in an otherwise empty Household while preserving the
  party-before-household-before-child order for moves between Households. Under
  those locks it rechecks that each Contact has no other current Household row.
- Household Membership creation locks every covered Person Contact in sorted
  order before checking overlapping Membership coverage, so concurrent family
  contracts cannot both pass the same date-range query.
- Party Link validation locks both accounting parties in sorted
  `(doctype, name)` order before checking either direction.
- Membership Ask settlement reads the observed linked voucher names without
  locking, then locks identity control, accounting configuration/control, the Ask, Economic Receipt/
  Source rows, any existing Sales Invoice, linked Payment Entries in deterministic
  name order, and financial child rows before rereading all monetary state. Every
  NPO Payment Entry path acquires its sole owner before the voucher; generic
  voucher mutation is rejected before core locks it. Hooks only recompute/queue
  settlement and never create the invoice recursively.
- Donation flows lock identity control, donation-accounting control, Company
  configuration, lineage root/Donation, Payment
  Intents sorted by name, Economic Receipt/observation/source rows, then vouchers
  and receipt claims. A callback may read Intent only to discover Donation, then
  locks Donation first and rereads Intent; it never holds Intent while acquiring
  Donation. Cancellation/amendment uses the identical order.
- Identity is the parent operational gate for all NPO finance. Donation accounting
  may become Active, and Membership Ask issuance/settlement may proceed in either
  mode, only while identity is Active at the same model epoch, approved migration
  run, and capability hash. Every financial writer acquires uncached shared permits
  in global order `identity -> donation-accounting when applicable -> Company
  donation/membership configuration -> domain owner -> voucher` and rechecks them
  immediately before commit. To fence/suspend identity, the controller locks it
  first, fences every dependent donation and Company membership/donation control in
  the same operation, then changes identity state; no dependent control may remain
  operational while identity is non-Active. Epoch/hash mismatch fails financial
  writes closed.
- Concurrent creation, archive/reactivate, Household move, and Party Link tests
  must prove one winner and deterministic retry behavior.

## 7. Household Redesign

### 7.1 Recommended definition

Household is a dated grouping of natural persons for shared mailing,
relationship, recognition, and optional household-level service rules. It is not
an accounting party by default.

### 7.2 Proposed Household Person child row

Replace the role-polymorphic `Household Member` target with a person-oriented
row containing:

| Field | Purpose |
|---|---|
| contact | Required Link to Contact |
| relationship | Household role such as primary, partner, child, dependent, or other; it is not an inferred legal relationship |
| from_date | Date membership started |
| to_date | Date membership ended; empty means current |
| is_primary | Primary household contact/person |
| receives_household_mail | Whether this person receives shared communication |

`Household Address Link` is likewise parent-owned and contains required Address,
address use (`Shared`, `Correspondence`, or `Other`), `from_date`, optional
`to_date`, and `is_default_correspondence`. Current defaults are unique under the
Household lock; history is ended rather than deleted. It creates no reverse
Dynamic Link on Address.

Household also gains controlled financial lifecycle fields (`financial_status =
Open | Closed`, immutable `financial_closed_from`, closure reason/audit link) and
explicit correspondence defaults (shared Address and language). The selected
Address must have a current Household Address Link row. Joint recipients are the
current Household Person rows marked `receives_household_mail`, ordered primary
first then by Contact; issuing a joint communication requires at least one
recipient and snapshots names, salutation, delivery endpoints, language, and
formatted Address instead of reselecting a generic Dynamic Link later.

The child DocType should be named `Household Person` to make its person scope
explicit. Replacement is conditional:

- Every deployed site runs and persists the Household preflight before schema
  activation.
- If all sites have zero Household rows, Household Member rows,
  `Customer.household` values, role household values, Contact-to-Household
  Dynamic Links, and Household-linked Addresses, a clean replacement is
  permitted.
- If any site has data, use the conversion fallback. Resolve each current or
  historical Household Member role to its canonical Person Contact, preserve
  dates and primary status, create Household Person rows, convert Household
  Address Dynamic Links to parent-owned Household Address Link rows, remove the
  reverse Contact/Address-to-Household projections after count reconciliation,
  and compare source/target counts before retiring the old rows.
- The fallback inventories standalone/conflicting `Customer.household`,
  Member/Donor household fields, Contact and Address Dynamic Links, and active
  Subscription links even when no Household Member child row exists. Rows from
  different roles that resolve to the same Contact and identical/contiguous
  interval coalesce into one Household Person; conflicting Household, interval,
  primary, or Address evidence becomes a blocking issue. Persist source-to-target
  cardinality and every coalescence decision before asserting count equivalence.
- A role that has no unambiguous Person Contact is a blocking migration issue;
  the migration must not choose by first email or first Dynamic Link.
- Development data may be reset only through an explicit operator command after
  export and only when the operator chooses reset instead of conversion. Install
  or migrate never resets it automatically. This migration shortcut is distinct
  from the separately enrolled, baseline-exported Good Demo reset contract in
  section 13.1.
- The Ilanga importer and its requirements/tests must move to Contact-based rows
  in the same coordinated release. Existing imported data is converted or
  deliberately reimported from its protected source; it is not silently lost.

### 7.3 Household invariants

- Only a Contact classified as `Person` may appear in Household Person.
- A Contact may have at most one current financial Household. Prior Household
  Person rows remain as dated history; moving or separation ends the old row before
  another current row begins.
- A Household may have at most one current primary person.
- Historical rows are ended with `to_date`, not deleted.
- Organization Customers and Suppliers cannot be Household people.
- Shared Address remains a standard Address referenced by dated Household Address
  Link; neither Contact nor Address stores a reverse Dynamic Link to Household.
- Current Household people and addresses are rendered only by the permission-
  aware Household loader after raw parent authorization, never by generic
  `load_address_and_contact` over reverse links.
- Member, Donor, and Volunteer forms may display a derived Household resolved
  through their canonical Customer/Contact, but must not own writable household
  state.
- Financial closure is a controlled operation, not an editable status toggle.
  From `financial_closed_from`, direct Desk/API creation of new Memberships,
  asks, Donations, invoices, receipts, or financial projections is blocked even
  if a caller backdates the document. Only a permissioned operation explicitly
  tied to a pre-closure source may settle, cancel/amend, reverse, correct, or
  issue an eligible historical receipt. Existing issued asks keep their payer.

Household validation locks all affected Person Contacts in sorted order before
it locks current Household Person rows. Sync reconciles both saved and persisted
prior rows so ending, removing, or retargeting a row cannot leave stale current
Household state; Address mutation also reconciles dated Household Address Link
rows under the Household lock. Concurrency tests must retain the current party-
before-household-before-child lock-order guarantee.

A household going apart is handled by ending dated Household Person rows and
creating or updating the resulting Households. It never splits or duplicates the
people's Contact, Member, Donor, Volunteer, Customer, or Supplier identities.

### 7.4 Family Membership and joint asks

Family Membership with one joint ask is an accepted Household use case. It must
be explicit rather than inferred merely because an Individual Member belongs to
a Household.

Membership gains a scope:

- Individual
- Organization
- Household

Proposed Membership fields are:

| Field | Rule |
|---|---|
| scope | Select: Individual, Organization, Household; required after migration activation and immutable after insert; a correction closes/replaces the Membership, while fenced migration may convert it only after locking the Membership and deleting incompatible DocShare rows in the same transaction |
| member | Existing required primary/administrative Member link |
| household | Required only for Household scope |
| payer_scope | Household or Covered Member; required for Household scope |
| billing_member | Required only for Covered Member payer scope; must be an active covered Individual Member |
| billing_customer | Household or Individual Customer matching payer scope; required before issuing any joint ask and immutable for its accounting documents |
| covered_members | Table of `Membership Covered Member`; allowed only for Household scope |
| cycle_namespace_key | Immutable, opaque, site-wide unique key assigned by the service; Membership Ask idempotency roots use this key rather than mutable document name |

Membership Type gains `collection_mode`:

- `Invoice` — dues are legally owed; create a standard Sales Invoice against
  `billing_customer`, while the rendered joint ask and correspondence are
  addressed to Household.
- `Request` — the ask is voluntary/non-ledger; do not create Accounts Receivable
  until payment or another accepted financial event establishes it.

The initial Household model does not use ERPNext Subscription. A Household
Membership whose Membership Type has `is_subscription` enabled is rejected;
repeat family billing is generated as idempotent Membership Ask cycles in the
selected collection mode. Existing Individual and Organization subscription
flows must set `Subscription.party` to the Customer matching the Membership
subject and may not fall back to a different Member or Customer. Supporting
Household Subscriptions later requires a separate design for generated-invoice,
ask-cycle, addressee, and payer synchronization.

The initial family Membership model uses one fixed gross amount. Invoice preview
sets `requested_amount = accepted_amount` before issue, and Request mode settles
only when linked advances cover accepted amount within normal currency precision.
A lower amount remains a Customer advance and never creates an implicit discount,
write-off, or reduced membership price. Variable pricing or different requested
versus accepted amounts require a separate explicit Membership Type policy.

`Membership Covered Member` contains:

| Field | Rule |
|---|---|
| member | Required Individual Member |
| contact | Read-only snapshot of that Member's canonical Person Contact |
| from_date | Required coverage start, within the Membership period |
| to_date | Optional coverage end, not before `from_date` and not after Membership end when set |
| coverage_role | Optional administrative label such as primary, partner, child, or dependent |

For Household scope:

- `household` is required.
- The existing `member` link remains the primary/administrative Member for
  compatibility and navigation.
- An explicit covered-Members child table links every person who receives the
  family membership rights. Each covered person has their own Individual Member
  role anchored to canonical Contact.
- `payer_scope = Household` creates or reuses the Household Customer and leaves
  `billing_member` empty.
- `payer_scope = Covered Member` requires `billing_member` and creates or reuses
  that Member's Individual Customer.
- Issuing a joint ask is the financial trigger that resolves and stores the
  matching `billing_customer` before the ask is sent.
- The joint ask is addressed to Household using its joint salutation and shared
  correspondence Address.
- The ledger party remains `billing_customer`; the Household is the membership
  scope and addressee, not an ERPNext accounting party.

The administrative `member` must be covered and belong to the selected Household
on the Membership start date. Every covered Member must be Individual and
anchored to the same Person Contact snapshot. In the initial model, each coverage
interval must be contained within that Contact's Household Person interval for
the selected Household; nonresident-dependent coverage is deferred until an
explicit eligibility policy exists. For Covered Member payer scope,
`billing_member` must also be covered and `billing_customer` must be its Person
Customer. For Household payer scope, `billing_customer.npo_household` must equal
`Membership.household`. Duplicate or overlapping coverage rows for one Member are
rejected. Two active Household Memberships of the same Membership Type cannot
cover the same Member over an overlapping period. Coverage changes are made by
ending and adding dated rows, not by rewriting prior periods.

Household membership changes must not silently rewrite active family Membership
coverage. The covered-Members rows are explicit historical evidence. Renewal may
propose the current Household people, while mid-term additions/removals require a
controlled update with effective dates.

Migration from the current inferred `is_household_membership` flag is
review-gated because that flag proves residence, not contractual coverage:

- Rows with `is_household_membership = 0` may infer Individual or Organization
  scope from the remediated Member subject type.
- Rows with `is_household_membership = 1` are blocking review items unless an
  approved source-specific rule identifies the Household and covered Members.
- The Ilanga source may provide such a rule, but its expected source/target
  counts and covered people must be asserted in migration tests.
- Until reviewed, the existing Membership remains readable under compatibility
  behavior and cannot be silently invoiced as a Household Membership.
- A linked active Subscription remains a legacy Individual/Organization billing
  contract against its existing exact Customer while review is pending; an
  inferred household flag does not retarget it. The audit inventories generated
  and open invoices. If review approves conversion to Household scope, close the
  Subscription at a controlled cycle boundary after open-item handling and start
  future Household Membership Ask cycles; never change the party on the existing
  Subscription in place.
- The old flag is removed only after every deployed row has an explicit scope
  and all Household coverage issues are resolved.

Existing Membership Type `collection_mode` is independently review-gated and is
never silently defaulted. Deterministic submitted invoice/Subscription evidence
may approve Invoice mode only when it proves the legal collection policy for that
type; every other eligible type requires a persisted operator decision. Null mode
preserves historical reading/settlement but blocks new Membership Ask issuance.
Mode changes create an effective-dated/versioned policy row, apply only to future
cycle roots after a controlled boundary, and never alter an issued Ask, existing
Subscription, invoice, or retry. Membership Ask snapshots that policy version.

One transfer from a verified joint account settles a Household-payer ask against
the Household Customer. A transfer from either partner may also settle the ask;
if the observed remitter differs from `billing_customer`, retain that evidence
without creating a second invoice or changing the historical Membership payer.

The joint communication and settlement state lives in `Membership Ask`, with at
least Membership, Household, payer scope, optional billing Member, billing
Customer, collection mode, cycle key, requested amount, accepted amount, Company,
currency, receivable/party account, advance-received account for Request mode,
membership Item, explicit quantity/rate, income account, gross/net and tax rows,
  rounding policy, cost center/project where used, issue/due dates, status, a unique ERPNext-only reference code, optional integration-owned external payment reference,
threshold-funded date, acceptance date, accounting posting date/override reason,
optional Sales Invoice, and linked Payment Entries. It also snapshots the joint
addressee, salutation, language, delivery Contacts/emails, and formatted postal
Address used when issued.

The initial Membership Ask model is Company-currency only in both Invoice and
Request modes. `accepted_amount` is the fixed gross Customer amount in that
currency. Ask
invoice builders disable unintended pricing rules/automatic discounts, use only
the snapshotted explicit Item rate/quantity and tax rows, and apply the
snapshotted rounding policy. After ERPNext calculates totals and before submit,
the effective payable (`rounded_total` when enabled, otherwise `grand_total`)
must equal accepted amount at currency precision; mismatch fails without
allocating advances or changing the ask price.

V1 positive purpose-owned charge and recovery invoices do not inherit live
Customer payment terms. After all mapping/default calls, the focused builder clears
`payment_terms_template` and any derived schedule, sets the frozen legal due date,
and writes exactly one 100% non-discounted Payment Schedule row; it rejects early-
payment discount or a core-introduced `payment_term` allocation. Fully funded
Request and On Receipt invoices use a due date no earlier than their approved
posting date. Invoice-mode asks and Receivable-on-Submit pledges use their
snapshotted legal due date. A later Customer or Payment Terms Template edit cannot
change an issued voucher. Purpose-marked Credit Notes follow ERPNext return
semantics: validation finishes with empty `payment_terms_template` and
`payment_schedule`, and standalone negative outstanding is settled without a
Payment Entry `payment_term` reference.

Every controlled Sales Invoice, Credit Note, and refund-recovery invoice sets
`set_posting_time = 1` and the approved `posting_date` plus valid `posting_time`
after mapper/default methods that can reset them. A builder using ERPNext
`get_payment_entry()` replaces its `nowdate()` with the approved cash posting/value
date before save. The service rereads and verifies date, time, due date, and the
document-type-appropriate empty or one-row terms/schedule immediately before
submit; drift rolls back the complete operation.

The immutable `cycle_root_key` identifies `Membership.cycle_namespace_key` plus
collection period, never `Membership.name`;
`attempt_no` and the unique full `cycle_key` distinguish controlled replacements.
At most one non-terminal or Settled attempt may exist for a root. A Reversed,
Refunded, Released, or Cancelled attempt can be superseded only through a locked
operation that links predecessor and successor, so retries reuse the same attempt
while a real recollection remains auditable.

`Payment Entry.membership_ask` provides the required direct reference independent
of Good Connector. `Sales Invoice.membership_ask` is a unique link so one ask can
produce at most one original charge invoice, including historical/cancelled
invoices. The field is `no_copy`; Sales Returns/Credit Notes leave it empty and
resolve the ask through `return_against` or a separate non-unique reversal audit
link, and set `npo_financial_purpose = "Membership Ask Reversal"`. Ordinary
invoice amendment/reissue on the same ask is blocked; correction
reverses the attempt and creates a linked successor. Financial and correspondence
context is immutable when the ask is issued. Every linked Payment Entry and Sales
Invoice must match the ask's Company, currency, party, and accounting dimensions.

An NPO-purpose Payment Entry is dedicated to exactly one immutable NPO financial
owner, not necessarily one reference row. Membership Ask permits only its one Ask
invoice. Membership Subscription permits only the invoice for one immutable
Membership billing-cycle owner and stores that cycle key on the Payment Entry.
Donation may add multiple controlled invoice references only when every
one resolves to the same Donation and Economic Receipt, such as the initial and a
later excess-acceptance event. No reference may resolve to a second Ask, second
Membership billing cycle, second Donation, or mixed NPO domain. A separately
tracked `Free Residual` or `Released`
amount may later receive ordinary same-Customer/Company/currency references, but
their total is capped by that disposition and cannot consume the NPO-reserved or
accepted allocation; all other ordinary mixing is rejected. Request advances
start with no standard reference and one `membership_ask`. Generic Payment Entry
insert/save/submit/cancel is rejected before `super()` when requested or persisted
references touch an NPO owner. The focused service discovers without locking,
acquires the relevant control/config and sole Ask/Membership-cycle/Donation owner
plus same-owner events/invoices first, then calls the standard voucher save so Payment Entry is
locked afterward, and rereads references, dispositions, and outstanding under
those locks. Ordinary non-NPO multi-reference Payment Entries are unchanged. This
removes scalar-owner ambiguity and prevents a Payment Entry hook from taking the
opposite Donation-versus-Ask lock order.

Membership Subscription owners distinguish `Subscription Cycle` from `Direct
Membership Cycle`. For a Subscription-backed original charge,
`Sales Invoice.subscription` must equal `npo_subscription`, and native `from_date`/
`to_date` must exactly equal the locked billing-cycle bounds; this registers the
same period with ERPNext's native duplicate-cycle detector. A direct non-
Subscription Membership invoice leaves all three native fields empty and uses its
distinct owner kind/key. First-bill migration either adopts the submitted invoice
as that native first cycle or advances the Subscription to the next unbilled period
under the same lock; it never leaves both generators eligible.

Native `Sales Invoice.subscription` belongs only to an original cycle charge.
Membership Subscription Credit Notes/recoveries leave it empty and retain only
base NPO owner/reversal links, so a return cannot become the current native invoice.
A managed Subscription adapter derives current invoice, outstanding, status, and
generation eligibility from original charge invoices plus net Payment Ledger and
cycle disposition: a partial reduction remains outstanding for its net due; a
fully credited/refunded/reduced cycle is terminal and does not block the next
period. Refund/reduction affects only that cycle; future cycles continue unless a
separate controlled Membership/Subscription end/cancel action sets the effective
boundary. The protected Subscription controller and scheduler intercept `process`,
`create_invoice`/`generate_invoice`, cancel, restart, force-process, and scheduled
entry points under identity/configuration/Membership/Subscription/cycle locks and
the unique root/attempt contract.

For an NPO-managed Subscription, party/Company/status, start/end/trial/current-
period dates, calendar/past-due/submit/generation timing, due days, cancel-at-end,
plan rows, tax templates, discounts, cost center/dimensions, and proration policy
are service-owned billing inputs. `Subscription Plan Detail.plan/qty` is parent-
only protected. Before creating a cycle root, the service locks identity and the
Company Membership Configuration, Membership, Subscription, selected Plan rows,
and cycle; it snapshots/fingerprints effective plan Item/rate/currency/interval,
quantity, tax/discount/due/dimension and period/cancellation inputs. Invoice
generation uses that cycle snapshot rather than mutable live values. A controlled
policy change is effective-dated for a future uncreated cycle and uses the same
locks; it cannot alter an open/issued cycle. Generic Desk/API/import/update-after-
submit edits and concurrent shared Subscription Plan drift either fail or force a
new reviewed plan version before future cycle creation.

Every real incoming transfer owned by a Membership Ask, in Invoice or Request
mode, first creates/reuses one immutable `Membership Ask Economic Receipt`.
Distinct transfers have distinct globally unique receipt keys. Standalone
`Membership Ask Economic Receipt Source` aliases map provider event IDs, Bank
Transactions, cash-receipt IDs, imported statement identities, and persisted
manual client request keys to exactly one receipt; amount/date/remitter similarity
is review evidence, never an idempotency key. A deterministic `Membership Ask
Receipt Observation Lock` serializes the Ask plus normalized Company/account/
currency/value-date/amount/source evidence while a new alias is assessed. Under
that lock, a provable existing transfer receives the new alias; ambiguous or
conflicting cross-channel candidates enter review and create no Receipt/Payment
Entry. Thus manual entry followed by Bank Transaction/provider import cannot
materialize twice merely because source IDs differ. A callback may read an alias only to
discover the Ask, then locks control/configuration, Ask, Receipt/Source, Ask
invoice/events, and Payment Entries in that order and rereads the alias. At most
one active incoming Payment Entry attempt represents a receipt; controlled Void/
Reissue retains predecessor history. Retries return the existing receipt and
voucher result instead of creating funding twice.

The Receipt snapshots immutable source timestamp/timezone, bank value date,
remitter evidence, reviewed Payment Entry posting date, and any closed-period
override reason. If the value date is open, PE posting uses it; if closed, the
Receipt enters Posting Review and no PE/funding exists until an authorized first-
open posting date is recorded. A retry never defaults to today. Threshold ordering
uses the immutable value date, while settlement verifies every advance posting
date is on or before the approved invoice posting date.

Cancelling a Payment Entry does not erase a confirmed Economic Receipt. Ask state
and net funding derive from receipt disposition plus submitted vouchers. An Ask
may become Cancelled only when no confirmed undisposed receipt remains; real funds
must first be refunded, released, or reassigned. This receipt record is
idempotency/audit evidence, not a parallel GL or editable allocation ledger.

`Payment Entry Deduction` and `Advance Taxes and Charges` are parent-only protected
children for every NPO-owned Payment Entry, and V1 requires both tables to be
empty. Deductions/advance-tax adjustments cannot silently settle an Ask/
Membership-Subscription/Donation
invoice with different cash or post fees/write-offs/taxes outside the approved
Credit Note/refund lifecycle. Provider/bank fees or withholding use a separate
approved expense/clearing/tax voucher that neither changes the NPO allocation nor
shares its refund/event key.

Membership Ask and Membership Subscription charge/reversal/recovery invoices
cannot be settled, reopened, written off, exchanged, or reconciled by ordinary
Journal Entry in V1. Journal Entry/Journal Entry Account validate, update-after-
submit, cancel, import, Payment Reconciliation, Process Reconciliation, and
Unreconcile guards reject any reference/allocation to those purposes, an Ask's
reserved payment, or a Subscription cycle outside its focused Payment Entry/
Credit Note lifecycle. Common-party automatic Journal Entries are likewise
excluded. Approved dues reduction uses the purpose-marked Credit Note; cash uses
the uniquely instructed Payment Entry. The only typed Membership Journal Entry
exception in V1 is the exact retained-credit NPO Credit Application matrix; it
cannot write off or exchange an original charge/reserved advance.

The Membership Type determines whether the joint ask creates a legally
collectible Sales Invoice or remains a non-ledger request until
payment/acceptance. It must never be represented as an unpaid Sales Invoice when
that Membership Type creates no legal receivable. In both modes the Household is
the joint addressee and coverage scope; `billing_customer` is the only ledger
party when accounting is created.

Settlement is explicit and idempotent:

- Invoice mode creates and submits one Sales Invoice against `billing_customer`
  for the accepted amount before sending the ask; normal Payment Entry
  allocation supports partial settlement. Overpayment allocates only the
  outstanding amount and leaves the residual as Customer credit or review under
  standard accounting policy. The invoice sets
  `npo_financial_purpose = "Membership Ask"`.
- Request mode creates no receivable when sent. It is enabled only when ERPNext's
  separate advance-liability accounting is configured for the Company and the
  snapshotted advance account is a Receivable-type account under the Liability
  root. Incoming transfers use dedicated submitted Customer Receive Payment
  Entries linked through ordinarily immutable `Payment Entry.membership_ask`;
  only the audited terminal-ask reassignment below may change it. Before
  settlement each such Payment Entry has no standard references and its complete
  unallocated party-account amount is reserved to that one ask. Partial or
  multiple transfers accumulate without an invoice. Once eligible advances cover
  the fixed accepted amount within currency precision, the same transaction
  inserts/reuses uniquely keyed `NPO Deferred Work` for Ask settlement. An after-
  commit enqueue only wakes the worker; loss between SQL commit and Redis enqueue
  is recovered by the Pending/expired-lease sweeper. The worker creates and
  submits one Sales Invoice with automatic advance allocation disabled and
  `npo_financial_purpose = "Membership Ask"`, applies only the linked advances
  through explicit standard Sales Invoice Advance rows, and verifies zero
  outstanding. A failed worker leaves durable retryable work and a funded Ask,
  with no partial invoice state.
- Request funding orders Payment Entries by verified value/posting date then
  creation/name. The currently eligible payment that crosses accepted amount
  freezes `threshold_funded_on` and legal acceptance date while that eligible set
  remains unchanged. Before an invoice exists, cancellation/reversal of a
  contributing payment locks the Ask and all linked payments, appends immutable
  threshold-crossing/reversal history, and recomputes in the same order. If the
  remainder stays funded, the new crossing payment replaces the current frozen
  date; if it falls below threshold, current acceptance/posting-review fields are
  cleared and state returns to Partially Funded or Issued. A later payment freezes
  the newly derived crossing date. Once an invoice exists, ordinary contributing-
  payment cancellation is blocked and only the controlled settlement-reversal
  path may change it. If the derived accounting period is open, the invoice uses
  the crossing date; if closed, the ask enters Posting Review and an authorized
  operator records the first permitted open posting date plus reason. A delayed
  settlement job never defaults revenue to today's date.
- Request mode V1 requires
  `Company.reconciliation_takes_effect_on = "Oldest Of Invoice Or Advance"`; any
  other value blocks issuance/settlement. Every allocated advance posting date
  must be on or before the frozen/approved invoice posting date. After standard
  Sales Invoice advance application, each generated
  `Payment Entry Reference.reconcile_effect_on` and the advance-liability-to-receivable GL transfer must
  equal that invoice posting date; mismatch rolls back the complete settlement.
  Effective setting changes remain fenced while dependent asks/payments exist.
- Enabling Request mode is an explicit Company-wide accounting decision because
  ERPNext's separate-advance switch affects unrelated Customer and Supplier
  advances. Preflight and activation cover existing Sales/Purchase Orders,
  Payment Entries, Payment Reconciliation, and regional accounting behavior.
  Snapshots are audit constraints, not overrides of ERPNext live resolution:
  while a non-terminal Request ask or any linked payment with Reserved,
  Reassignment Pending, or Refund Pending disposition exists, hooks block changes
  to the Company switch,
  Company/Customer/Customer Group advance-account precedence, relevant account
  type/currency, and reconciliation effect-date policy when they would change
  that ask's effective configuration. Operators must settle, refund/release, or
  explicitly migrate/reissue affected asks before such a change.

A normal `NPO Membership Accounting Configuration` row per Company is the shared
database mutex and explicit operator opt-in. Ask issuance locks it before reading
live Company/Customer/Customer Group/Account/Accounts Settings, snapshots the
resolved values, inserts the Ask, and rechecks under the same lock. Every relevant
configuration mutation resolves affected Companies, locks their configuration
rows in sorted order, and performs the same dependency check. Thus first-Ask
issuance cannot race a setting change merely because neither saw an earlier open
Ask.
- Request-mode underpayment remains an advance and marks the ask Partially
  Funded. Overpayment allocates only the accepted amount and leaves the residual
  as Customer credit/refund review. The system never silently changes the
  membership price, discounts the invoice, or writes off a difference to match a
  transfer.
- A third-party remitter may pay, including another covered partner, but the
  invoice party remains `billing_customer`; remitter identity is retained as
  payment evidence.
- An unidentified or conflicting payer remains in reconciliation review. The
  system never changes `billing_customer` merely to force an automatic match.

Ask, party account, advance account, receivable account, Payment Entries, and
Sales Invoice must use Company currency; FX aggregation is deferred. Funding is derived from submitted,
non-cancelled linked Payment Entries in deterministic posting-date/creation/name
order; no operator-editable parallel allocation table is introduced. Standard
Payment Reconciliation cannot consume a reserved Payment Entry, split it across
asks, or alter the ask-invoice allocation. Guards cover Payment Entry validate,
`before_update_after_submit`, cancellation, Sales Invoice cancellation, Payment
Reconciliation, Process Payment Reconciliation, and Unreconcile Payment paths.
`Payment Entry.membership_ask_fund_disposition` is a maintained read-only value:
`Reserved`, `Reassignment Pending`, `Refund Pending`, `Allocated`, `Free
Residual`, `Released`, or `Refunded`. Reversed asks with valid unreassigned cash
remain Reassignment Pending, not generally reconcilable merely because the Ask
is terminal. Only Free Residual/Released amounts may enter ordinary Customer
reconciliation; accepted ask allocations remain immutable.

An upgrade-tested Frappe v16 Payment Reconciliation extension calls `super()`
and excludes Membership Reserved/Reassignment Pending/Refund Pending and Donation
Excess Pending rows before applying
the user's payment limit. Because core limits before returning candidates, the
mixin temporarily overfetches in increasing deterministic bounds (or unbounded
when no limit was requested), filters, then restores and reapplies the original
limit; reserved rows cannot hide a valid later candidate. Mutation guards remain
defense in depth so automated reconciliation neither selects a reserved row nor
fails the whole job.

A Frappe `before_job` sanitizer is registered specifically for ERPNext's
hard-coded Process Payment Reconciliation `reconcile` function, because a DocType
mixin cannot intercept that module-level background call. It first acquires a
process-specific MariaDB named lock, reads the next allocation group without row
locks, and resolves every immutable Ask/Membership-cycle/Donation owner. It then locks activation/
configuration, owners and same-owner events/invoices, Payment Entries, and finally
the exact Process Payment Reconciliation Log Allocations rows in deterministic
order. Changed group/owner/disposition/reference/outstanding rolls back and
restarts discovery. Stale rows are marked skipped idempotently with reason and
parent counts in a short committed sanitizer transaction, then discovery restarts
while the named process lock remains held. For the first valid group, owner and
Payment Entry locks remain open, an exact request-local operation sentinel is set,
and core reconciliation runs. If no group remains, core counts are updated so its
no-work path runs while custom skipped counts retain `requires_rerun`. The named
lock is released in success/failure cleanup.
Skipped cash becomes eligible only in a future Process run after controlled
release/reassignment. Thus stale rows neither reach core nor fail unrelated
allocations. Custom skipped-count/reason and `requires_rerun` fields on the
Process/Log prevent core's eventual Completed status from being presented as
“all candidates reconciled”; the operator sees a completed-with-skips outcome and
starts a fresh run after disposition changes.

The sanitizer has its own bounded retry/failure contract because Frappe invokes
`before_job` outside the core method's try/finally. Each attempt starts from a
fresh transaction; a deadlock or exception performs full rollback so no partial
skip/count mutation survives. Transient failures retry with fresh locks. On final
failure, a fresh status-only transaction records sanitizer error/retry count and
queues a distinct bounded retry or pauses for operator action, then raises to
suppress the core reconcile function. It never returns control to core after an
incomplete sanitizer pass.

Sales Invoice automatic advance allocation is guarded separately. A v16 Sales
Invoice extension calls `super()` and filters Membership-Ask Reserved,
Reassignment Pending, and Refund Pending plus Donation Excess Pending Payment
Entries from advance candidates,
except that the exact owning Ask settlement invoice may use its Reserved entries
through the explicit advance rows built by the settlement service. Validate and
before-submit hooks lock every referenced Payment Entry in sorted order and reject
manual/import/REST advance rows belonging to another Ask, an unrelated invoice,
or an invalid disposition. Automatic allocation on ordinary invoices can never
steal an ask reserve between candidate discovery and submit.

The same composable Sales Invoice extension overrides
`process_common_party_accounting`: every NPO financial purpose skips ERPNext's
automatic Party-Link Journal Entry, while unmarked invoices call `super()`.
Purpose-specific credit-limit policy is explicit and snapshotted. Fully funded
Request and On Receipt invoices bypass credit-limit checking only after their
locked cash invariants pass; Invoice-mode Membership Ask and pledge receivables
enforce the Customer limit unless their restricted Company configuration
explicitly approves bypass. All unmarked invoices retain core behavior.

Every ask-link assignment and Payment Entry submit discovers the Ask without a
lock, then locks configuration/control and Ask before Payment Entry, rechecks
party/configuration/references, and rejects terminal states. The settlement job
locks the Ask before the initially observed Payment Entry names, requeries the
linked set, and rolls back/retries if it changed before settlement.
This makes a concurrently submitted late payment either part of the locked set or
a rejected/reviewed payment after the ask becomes terminal.

Membership Ask states are `Draft`, `Issued`, `Partially Reduced`, `Reduced`,
`Partially Funded`, `Settlement Pending`, `Posting Review`, `Settled`, `Refund
Pending`, `Partially Refunded`, `Refunded`, `Released`, `Cancelled`, and `Reversed`:

| State | Derived contract |
|---|---|
| Draft | No submitted invoice or linked payment |
| Issued | Invoice mode has its submitted unpaid invoice with no reduction or retained cash; Request mode has zero eligible net funding |
| Partially Reduced | A no-cash applied Credit Note reduced, but did not eliminate, the legal amount due and no cash is retained |
| Reduced | No cash was received/retained and applied Credit Notes reduced the complete legal amount; this is terminal unless a controlled recovery creates a forward charge |
| Partially Funded | Retained accepted cash is positive but below the current net legal amount due, whether or not a separate reduction also exists |
| Settlement Pending | Request funding meets threshold and the idempotent settlement job has not committed |
| Posting Review | Funding threshold is met but the derived accounting period is closed and requires an approved posting date |
| Settled | Original invoice is submitted, retained accepted cash covers the positive net legal amount due, and outstanding is zero; a no-cash reduction alone never qualifies |
| Refund Pending / Partially Refunded | A controlled outgoing refund/correction has started or returned only part of the funded/settled amount |
| Refunded | All accepted/funded money was returned through submitted standard vouchers |
| Released | Pre-invoice Request advances were deliberately released as ordinary Customer credit |
| Cancelled | No submitted original invoice, non-cancelled linked Payment Entry, or confirmed undisposed Membership Ask Economic Receipt remains; cancelled/failed pre-settlement attempts are retained as audit |
| Reversed | Clerical settlement reversal completed; terminal and supersedable |

Invoice-mode state is recomputed from the original Sales Invoice, Payment Ledger,
Credit Notes, Refund/Reversal Instructions, forward recovery invoices, recovery
payments, and outgoing refunds into separate immutable-derived dimensions:
`gross_legal_due`, `receivable_reduced`, `recovery_charged`, `net_legal_due`,
`cash_funded`, `cash_refunded`, `cash_recovered`, `retained_cash`, and aggregate
`outstanding`; `retained_cash = cash_funded - cash_refunded + cash_recovered` with
each recovery capped by its reversed refund tranche. A submitted collectible-
reduction/retained-credit recovery charge
reverses only its linked reduction in `net_legal_due`; if no cash is retained its
state returns from Reduced to Partially Reduced or Issued according to the
remaining unrecovered reduction, then normal recovery cash derives Partially
Funded or Settled. A cash-gated recovery with no confirmed cash leaves its prior
refund disposition plus pending reversal instruction and creates no false due.
State precedence is controlled
refund/reversal terminal state, no-cash Reduced, Settled, Partially Funded,
Partially Reduced, then Issued. Request eligible net funding is the submitted
dedicated incoming advances less submitted ask-linked refunds/releases, never a
manually edited total. Refunded requires submitted outgoing cash; an unpaid applied
Credit Note never produces Partially Funded, Settled, or Refunded. A partially
funded or expired Request cannot be cancelled
while real cash remains. A controlled Abandon operation either refunds it through
standard outgoing Customer Payment Entries tied to the original advances, or,
with explicit accounting permission, releases the unallocated amount as ordinary
Customer credit; both preserve the incoming receipt and make the attempt
terminal. If every pre-settlement incoming Payment Entry was cancelled and every
receipt is unconfirmed or terminally void with zero funds, Abandon instead
verifies zero net cash under all locks,
marks the attempt Cancelled, preserves those cancelled links, and permits only the
normal audited successor-attempt path.

After settlement, ordinary cancellation/unreconciliation of the original invoice
or accepted allocations is blocked. A restricted Void Settlement operation uses
standard unreconciliation and cancellation for clerical error. Valid unallocated
cash may be moved to an approved successor ask only by a controlled reassignment
that locks both asks and Payment Entry, validates identical payer/company/
currency/accounting context, changes the otherwise immutable ask link, and writes
an immutable reassignment audit. Real refunds preserve the trail through standard
Credit Notes where revenue/dues are reduced and outgoing Payment Entries; a mere
payment reversal that leaves an invoice enforceable reopens its outstanding
instead of creating a Credit Note. Residual overpayment becomes ordinary Customer
credit only after the accepted ask amount is immutably allocated.

Every Membership Ask, Membership Subscription cycle, or Donation refund/release/
chargeback tranche first creates
or reuses a service-owned `NPO Refund Instruction`; voucher creation is never the
idempotency authority. The instruction stores one immutable globally unique
internal `refund_key`, domain/parent/root event, source amount/currency, requested
tranche amount, reason/kind, status, original receipt/payment/invoice, immutable
economic refund/source timestamp and timezone, recognition posting date, cash
value/posting dates, separate closed-period override reasons, and scalar links to
its Credit Note, outgoing Payment Entry, or Holding Refund Journal Entry as
applicable. No retry/callback defaults a date to today. Standalone `NPO Refund
Source` aliases have globally unique
namespaced external/operator request keys and map retries, provider refund IDs,
and chargeback/dispute IDs to exactly one instruction. Operator commands persist a
client request key before voucher work; provider callbacks must supply their
provider event/refund key. A second distinct partial refund gets a new instruction
and tranche key, while retrying either returns the existing result.

Voucher-side `npo_refund_instruction` links are service-owned and uniquely
constrained per voucher DocType; an instruction may own the exact Credit Note plus
outgoing Payment Entry pair, or one Holding Refund Journal Entry, but never two of
the same voucher role. Cancellation of a refund creates a separately keyed linked
reversal instruction rather than clearing/reusing the original key. The service
locks the owning Ask/Membership cycle/Donation and source economic/payment event
first, then Refund
Instruction/Source rows, then vouchers and receipt claims; it recomputes already-
refunded amount before every submit. Credit Note posting uses the instructed
recognition date; outgoing Payment Entry uses the cash posting/value date and
preserves source reference number/date. At currency precision, Credit Note
effective payable where present, party-account movement, reference allocation,
outgoing cash, or Holding JE debit/credit must equal the instructed tranche as the
case matrix requires. Instruction, aliases, and keys are immutable
audit and cannot be renamed, discarded, or deleted. This contract covers manual,
gateway, EBICS, chargeback, Abandon, excess, accepted-gift, and receipt-correction
paths.

The V1 refund/reduction reference and account matrix is fixed:

Every NPO charge line uses a refund-compatible non-stock Item/UOM configuration.
Activation verifies `must_be_whole_number = 0` for both effective transaction and
stock UOMs, conversion-factor representability, and the effective `qty`/`stock_qty`
DocField or site Float precision. The configured rate/quantity scheme must
represent every supported Company-currency minor-unit tranche; whole-number,
conversion, global precision, or Property Setter drift blocks activation/issuance.
The original invoice snapshots refundable quantity, rate, tax basis, rounding
residual, source Sales Invoice Item name, and cumulative returned quantity.
Every Credit Note item sets exact `sales_invoice_item` to that source row; empty,
wrong-invoice/item, copied, or changed links are rejected. Partial/split Credit
Notes allocate disjoint remaining quantities per source row with a deterministic
cumulative proration/remainder algorithm so their sum never exceeds the original,
ERPNext's return-quantity validation runs/passes, and each effective payable equals
its instructed currency tranche. If no valid quantity/tax split can produce the
requested amount, the service rejects it rather than changing rate/tax or
bypassing core validation.

| Case | Required ERPNext vouchers and references |
|---|---|
| Accepted Membership/Donation cash refund | Standalone purpose-marked Credit Note with `is_return = 1`, `return_against` the charge, and `update_outstanding_for_self = 1`; Customer Pay Payment Entry uses bank/cash/clearing against the original receivable and references only that same-owner Credit Note for its exact negative outstanding |
| Unpaid dues/pledge reduction | Applied Credit Note with `update_outstanding_for_self = 0`, capped by locked positive original-invoice outstanding; no Payment Entry or Journal Entry |
| Reduction spanning open and paid amounts | Atomic split into one applied Credit Note for the open portion and one standalone refundable Credit Note plus outgoing Payment Entry for the paid portion, each with a distinct linked Refund Instruction |
| Request advance or Request overpayment refund | No Credit Note; submit Customer Pay Payment Entry unreferenced on the source's snapshotted advance-liability account, then owner-locked Payment Reconciliation treats that outgoing Pay entry as the invoice and the original incoming Receive entry as payment, capped by refundable disposition |
| Invoice-mode Membership overpayment or Donation excess refund | No Credit Note; submit Customer Pay Payment Entry unreferenced on normal receivable, then use the same owner-locked reverse-payment reconciliation against the original incoming Receive entry, capped by exact Free Residual/Released/excess disposition |
| Paid reduction retained as Customer credit | Standalone Credit Note with `update_outstanding_for_self = 1` and no outgoing Payment Entry; Refund Instruction kind is `Retained Credit`, disposition becomes `Credit Released`, and only the typed NPO Credit Application may consume its exact negative outstanding |
| Held Donation refund | One typed Holding Refund Journal Entry, `Dr Refundable Donation Receipts / Cr exact Gateway Clearing`; no Customer reference, Credit Note, or Payment Entry |
| Chargeback while invoice remains enforceable | No Credit Note; create a uniquely instructed Customer Pay Payment Entry from the exact bank/provider clearing account on provider chargeback posting date, unreconcile the original Receive from its invoice, and reverse-reconcile that original Receive against the new Pay; invoice reopens and retained partial allocation is split/rebuilt under lock |
| Accepted-gift chargeback that extinguishes the gift | Create/reconcile the same chargeback Pay voucher so provider cash removal is posted, then submit an applied Credit Note for the reopened original-invoice outstanding; no second outgoing voucher |

An Ask/Membership-cycle/Donation-owned refund Payment Entry may reference its exact same-owner
reversal Credit Note or reverse Payment Entry under this matrix; the ordinary
owner/reference restrictions still reject every other domain. Both Credit Note
modes are built from exact original item/tax/rounding snapshots and verify rounded
effective payable. Never call ERPNext's generic debit/credit-note reconciliation,
which can create a forbidden system Journal Entry. An applied Credit Note must
reduce original outstanding exactly and retain no independent outstanding; a
standalone refundable Credit Note must leave original outstanding unchanged until
its instructed outgoing Payment Entry clears the exact negative balance or the
Retained Credit operation explicitly releases it. Reverse Payment Entries are
submitted unreferenced exactly as ERPNext's tested reverse-payment flow requires;
`NPO Refund Instruction` and service-owned
`Payment Entry.npo_reverse_source_payment_entry` carry ownership/idempotency, not
the standard references table. Reconciliation then adds the standard Payment-
Entry-to-Payment-Entry relationship in the tested direction: outgoing Pay is the
invoice side and original incoming Receive is the payment side. Request refunds
use the liability account core already selects. For normal-receivable refunds or
their recovered-cash reversal on a Company with separate advances enabled, one
narrowly scoped cooperative `set_liability_account` extension preserves
receivable only when a locked Refund/Reversal Instruction, source/disposition/
account matrix, and operation sentinel match; it
calls `super()` unchanged for every other Payment Entry and never admits a direct
Donation reference. The service verifies account and amount after core validation.
Refund cancellation unreconciles this reverse-payment pair before cancelling or
forward-reversing either voucher.

Retained Credit is not exposed to ordinary or Process Payment Reconciliation,
because ERPNext would create an unowned debit/credit-note Journal Entry. A locked,
idempotent `NPO Credit Application` service owns that narrow exception. Its
immutable unique application key links Refund Instruction, source standalone
Credit Note, target positive Sales Invoice, amount, approved open posting date,
dimensions, and one purpose-marked Journal Entry whose `voucher_type = "Credit
Note"` as required by ERPNext validation. The JE has exactly two Customer
rows on the same receivable/account/currency: one references the target invoice
and one the source Credit Note, with equal opposite amounts and no income, cash,
write-off, exchange, or deduction row. It discovers every source/target NPO owner
without locking, locks all owners in deterministic `(domain, name)` order, and
only then locks source Credit Note, target invoice, application, and JE. It
rechecks released credit/positive outstanding and supports partial applications
with distinct keys. Manual JE, Payment Reconciliation, and Process paths remain
blocked. An open-period cancellation first cancels dependent Credit Application
JEs and restores their source/target outstanding. A closed-period refund undo
leaves applications and original vouchers intact and uses the forward-charge path
below; it never attempts an opposite JE against a zero-outstanding Credit Note.

Refund cancellation always uses the separately keyed reversal instruction and
classifies the original disposition before creating a voucher. If all refund
vouchers are legally cancellable in an open period and any external cash reversal
is confirmed, the service locks/reverses receipt corrections, cancels dependent
Credit Application JEs, unreconciles/cancels the outgoing Payment Entry, cancels
the applied/standalone Credit Note, and verifies original outstanding/recognition.
Otherwise the original vouchers remain and the forward path is fixed:

- Reversing an unpaid legally collectible dues/pledge reduction creates a uniquely
  linked `Membership Ask Refund Recovery`, `Membership Subscription Refund
  Recovery`, or `Donation Refund Recovery` Sales Invoice on the approved open date
  without a Payment Entry. It restores the
  receivable and recognition; later cash settles it normally.
- Reversing an On Receipt reduction, accepted-cash refund, Request advance refund,
  excess refund, or Holding refund creates no accounting voucher until returned
  cash is confirmed. Then On Receipt/cash-refund recovery atomically creates the
  purpose-marked forward invoice and Receive Payment Entry; advance/excess recovery
  unreconciles the original Receive/outgoing Pay pair, creates a newly keyed
  recovery Receive, and reconciles it against the still-submitted outgoing Pay;
  Holding recovery creates a new Holding Capture. The original owner disposition
  is restored only in that same transaction. The narrow account extension
  preserves normal receivable for applicable recovery Receives under separate
  advances, while Request recovery uses its snapshotted liability account.
- For unconsumed Retained Credit in a closed period, a purpose-marked forward
  recovery charge restores recognition and the typed Credit Application consumes
  that exact remaining Credit Note balance against the charge. If the retained
  credit was already partly/fully applied, existing target applications remain;
  the forward charge for the consumed amount stays collectible and cannot be
  netted through an opposite JE or a zero-outstanding Credit Note.

No-cash recovery remains Pending only for dispositions whose recovery legally
depends on returned cash; it does not suppress the collectible-reduction or
retained-credit forward charge above. Each forward voucher equals its instructed
tranche at currency precision, carries only the recovery purpose/reversal
instruction/original Credit Note links, and triggers any required receipt
correction reversal.

The jurisdiction-neutral unique reference code and permissioned non_profit manual Payment Entry
search/builder/submit service are always available with ERPNext and `non_profit`
alone; generic voucher mutation remains blocked. The Good NPO Swiss presentation
may request QR/QRR behavior from Good Connector, which owns generation, validation,
EBICS matching, and automatic Bank Transaction linking. Family Membership
correctness and manual settlement do not depend on either app.

Under that Swiss adapter, QRR has exactly one active owner per mode. Invoice mode assigns QRR only to the
Sales Invoice; Membership Ask stores no competing active identity and bank
matching returns the invoice. Request mode assigns QRR to Membership Ask before
an invoice exists; its later immediately settled invoice leaves QRR empty and is
never a second candidate. The Ask owner becomes inactive when settled,
refunded/released, cancelled, or reversed. Good Connector's Company-serialized
QRR registry/collision scan is extended to active Membership Ask alongside Sales
Invoice and legacy Donation identities; without Good Connector, only the internal
unique reference is used.

### 7.5 Household donations and receipts

Joint Household giving uses the existing accounting chain through an optional
Household Customer; Household itself is not registered as a custom ERPNext Party
Type.

```text
Household
  -> Household Donor
  -> Household Customer
  -> Donation
  -> Sales Invoice (customer = Household Customer)
  -> Payment Entry (references Sales Invoice)
```

`Donor.subject_household` is the fundraising/recognition anchor.
`Donation.customer` is the immutable accounting payer and points to the same
Household Customer for joint giving. This produces one joint giving history
without merging the people or their Individual Customers. New Customer-regime
Payment Entries never reference Donation directly; standard accounting runs
through one or more Donation-linked Sales Invoices as defined in section 8.

The model distinguishes:

| Concept | Stored identity |
|---|---|
| observed remitter | Bank Transaction/Payment Entry evidence |
| accounting payer | `Donation.customer` |
| fundraising recognition | `Donation.donor` |
| receipt recipient | immutable recipient Customer/address snapshot on Donation Receipt |

A verified joint bank account may be a standard Bank Account with
`party_type = "Customer"` and `party = Household Customer`. Joint account
ownership is strong evidence for Household payer matching, but does not by itself
authorize joint Donor creation or a joint tax receipt. The base model exposes an
explicit Household Donor plus Household Customer recipient candidate with an
immutable joint-name/address snapshot; the selected jurisdiction provider decides
legal entitlement. The Switzerland V1 policy in `good_npo` approves that joint
recipient path, never inference from remitter or shared-address evidence.

An individual may pay a Household-recognized gift or a Household account may pay
an individually recognized gift only through an explicit reviewed third-party
payer path. Automatic matching never changes recognition merely because the
remitting IBAN is joint.

### 7.6 Financial Household separation

The old Household and its Customer represent the historical joint unit. On
separation:

- Through the controlled closure operation, lock Household and its projections,
  set `financial_status = "Closed"` and immutable `financial_closed_from`, and
  record the separation audit before permitting new projections elsewhere.
- End Household Person rows with effective dates.
- Stop new Memberships, asks, Donations, invoices, and receipts against the old
  Household Customer from the separation effective date. Do not wait for open
  obligations, advances, or credits to be resolved before applying this block.
- Continue only controlled settlement, allocation, cancellation/amendment,
  corrections, and legally eligible historical receipt issuance for
  pre-separation activity against the preserved Customer.
- Preserve the old Household Customer, Household Donor, Bank Account links,
  Membership Asks, Sales Invoices, Payment Entries, Donations, receipts, and
  giving history.
- Create new Household records and Customer projections only when future
  financial activity requires them.
- Never repoint the old Household Customer to one resulting Household or move
  submitted accounting to either person.
- Existing issued asks keep their snapshotted payer; renewals use the new
  Household structure.

## 8. Donation Accounting Decision

The accepted direction is for Customer to be the standard accounting party for
new membership and donation money, while Donor remains the fundraising role and
Donation remains the non-ledger gift, pledge, recognition, and reporting record.
Requirement activation and per-site cutover remain blocked until the complete
production-accounting preflight confirms whether the legacy regime is required.

A Customer Payment Entry must not reference Donation directly. Merely admitting
Donation in `PaymentEntry.get_valid_reference_doctypes()` would still fail
ERPNext's Payment Ledger outstanding validation because Donation creates no
originating receivable, and bypassing that check would credit receivables without
crediting donation income. New Customer-regime accounting therefore uses standard
Sales Invoice and Payment Entry vouchers; no mixin admits Donation as a standard
Payment Entry reference or bypasses outstanding validation. The cooperative v16
Payment Entry extension contains the cross-cutting lifecycle guard plus only the
narrow Refund-Instruction `set_liability_account` exception defined in section
7.4 for an unreferenced outgoing receivable refund or reversal-instruction
recovery Receive under separate advances. It
calls `super()` unchanged for all other references/posting/reconciliation and its
effective MRO/behavior hash is activation-gated.

Customer-regime Donation fields and links are:

1. `Donation.customer` is the immutable accounting payer. Resolve or create it
   from the Donor subject before the first financial posting: Person Customer for
   Individual, organization Customer for Organization, Household Customer for
   Household, or the controlled Anonymous Customer.
2. `Donation.accounting_model` is immutable and distinguishes `Legacy Donor
   Direct` from `Customer Invoice`. Immutable `accounting_party_type` and
   `accounting_party` snapshots retain the exact Donor or Customer used by that
   model. `Donation.accounting_namespace_key` is an immutable, opaque, site-wide
   unique service key used by event roots instead of mutable document name.
3. `Donation.accounting_timing` is immutable for Customer Invoice rows:
   `On Receipt` for an ordinary voluntary/cash gift or `Receivable on Submit` for
   an unconditional pledge that accounting policy permits as a receivable.
4. `Sales Invoice.donation` is an indexed many-to-one Link and each generated
   invoice stores an immutable, site-wide unique `event_attempt_key`. Donation
   Accounting Event separates stable `event_root_key`, `attempt_no`, unique
   attempt key, and nullable unique active-root key. Roots use immutable service
   keys: `DONATION:<accounting-namespace-key>:PLEDGE`,
   `RECEIPT:<economic-receipt-key>:INITIAL`, or
   `RECEIPT:<economic-receipt-key>:EXCESS:<decision>`. Void/Reissue closes the active
   attempt and increments attempt number without colliding with retained history.
   `Donation Economic Receipt` is the canonical one-real-incoming-payment record
   with a globally unique `economic_receipt_key`, and standalone
   `Donation Economic Receipt Source` rows attach globally unique source aliases
   such as manual entry, gateway charge, imported Bank Transaction, or cash
   receipt. Exactly one active attempt per event root may recognize an economic
   receipt slot; excess decisions use child roots under the same receipt. Manual
   cash/bank entry creates and locks the economic receipt first rather than
   trusting a request-local token. Creation locks Donation, economic receipt, and
   source rows in deterministic order and relies on database unique keys as the
   final retry/concurrency guard. A pledge normally has one invoice; On Receipt
   may have one invoice per accepted root/child event.
5. Generated invoices use a configured non-stock donation Item, donation income
   account, Company, currency, receivable account, dimensions, and tax treatment
   snapshotted from approved settings. Every invoice Customer must equal
   `Donation.customer`, sets `npo_financial_purpose = "Donation"`, and every
   Payment Entry references the Sales Invoice, not Donation.
6. `Donation Payment Intent` is the provider-neutral checkout record with
   Donation, provider/source identity, amount/currency, independent
   `provider_status` (`Pending`, `Authorized`, `Captured`, `Refund Pending`,
   `Partially Refunded`, `Refunded`, `Expired`, `Revoked`), and accounting totals
   for captured, held, reclassified, and refunded amounts. Derived disposition is
   `Uncaptured`, `Held`, `Partially Disposed`, or `Fully Disposed`; one capture may
   be split between accepted/reclassified and refunded tranches. Provider IDs are
   unique, totals derive from immutable provider evidence and Holding vouchers,
   and net reclassified versus held/refunded amounts are exposed as immutable
   receipt-policy facts; base does not decide legal eligibility.

`NPO Donation Accounting Configuration` is the governed Company policy/mutex, not
only an account lookup. Its states are `Disabled`, `Fenced`, `Active`, and
`Suspended`; it stores the default and allowed timing policy plus configuration/
capability version. `Donation.accounting_timing` is read-only and service-derived
from that policy and reviewed pledge evidence. Guest/API payloads and compatibility
rows cannot select Receivable on Submit. Every Donation writer locks identity,
donation-accounting, then this Company row before reading policy or masters.
Configuration and referenced Company/Customer Group/Account/Item/UOM/Tax/Payment
Terms/precision mutations take the same locks, apply only to future event roots,
and fence, finish, or explicitly migrate every dependent open Intent, Receipt,
event, refund, and deferred job before a changed row returns Active. Missing,
Disabled, Fenced, Suspended, stale, or corrupt configuration fails new accounting
closed; historical correction uses its immutable snapshot under the matching
permit.

`Donation Accounting Event.accepted_amount` is the gross Customer payable.
Invoice builders use explicit Item quantity/rate and snapshotted tax rows, disable
unintended pricing rules/discounts, apply the approved rounding policy, and verify
that effective payable (`rounded_total` when enabled, otherwise `grand_total`)
equals accepted amount at currency precision before either invoice or payment
submits.

Captured funds that cannot yet be attributed/accepted are accounting events, not
merely review flags. The Company config snapshots Gateway Clearing and Refundable
Donation Receipts liability accounts. A service-owned `Donation Holding Capture`
Journal Entry posts `Dr Gateway Clearing / Cr Refundable Donation Receipts` on
the reviewed posting date and links the Economic Receipt/Intent; it creates no
income and reports a Held disposition to the receipt policy provider. Later acceptance creates the Donation Sales
Invoice and a controlled `Donation Holding Reclassification` Journal Entry
(`Dr Refundable Donation Receipts / Cr Customer Receivable` against that invoice).
Refund instead uses `Donation Holding Refund` (`Dr Refundable Donation Receipts /
Cr Gateway Clearing`). Partial accept/refund splits only the remaining held
amount. All three use immutable account/date/amount/source snapshots, unique
event keys, standard GL/Payment Ledger where applicable, and mutation fences.

The initial Customer Invoice model is Company-currency only. `Donation
Accounting Event` freezes verified source timestamp/value date/timezone, legal
payment date, accounting posting date, source/Company currency and amount,
accepted/excess/refunded amounts, account currency, and source provenance. Never
default a delayed callback to today. Use the verified funds-availability/value
date when its accounting period is open; a closed-period event enters review and
requires an authorized first-open-date posting decision with reason while
retaining the actual payment date for receipt policy. Foreign-currency/FX
recognition is deferred to a separate design.

Cross-source observation never creates a second economic receipt automatically.
An imported Bank Transaction first looks for an exact source alias or existing
manual Payment Entry/economic receipt and links/reconciles that record; an
amount/date/remitter fingerprint is review evidence, not proof, and blocks new
materialization when ambiguous. A gateway provider payout settles the gateway
clearing account and is not another donor receipt. Concurrent manual-to-EBICS or
gateway-to-bank observations also acquire a deterministic `Donation Receipt
Observation Lock` keyed by Company bank/gateway account, currency, amount, value
date, and normalized available reference/remitter evidence. The lock serializes
cross-source candidate checks without declaring the fingerprint unique: the
second observation reuses an exact identity or remains in review, while staff may
later approve two genuinely distinct identical receipts. Manual bank entry must
capture the authoritative bank reference when available. Source aliases,
economic-receipt key, and observation lock together prevent the race from
creating two accounting events.

The accounting flows are:

- `Receivable on Submit`: submit one Sales Invoice for the legally recognizable
  pledge amount (`Dr Receivable / Cr Donation Income`). Standard Customer Payment
  Entries may settle it partially or fully.
- `On Receipt`: submitting Donation or starting checkout creates no receivable.
  Each confirmed and accepted bank, cash, or gateway receipt atomically
  creates/submits a Sales Invoice for the accepted amount and a standard Customer Payment Entry
  against it (`Dr Bank or Gateway Clearing / Cr Donation Income` after the
  temporary receivable nets to zero). Multiple partial receipts may create
  multiple event-keyed invoices; retries cannot duplicate either voucher. When a
  bank event exceeds the accepted gift, the Payment Entry records the real full
  receipt but allocates only the accepted invoice amount and leaves the residual
  as ERPNext's standard unallocated Customer credit in the receivable party
  account pending review. V1 explicitly accepts that negative-receivable
  presentation; it does not claim that a mixed referenced/unallocated Payment
  Entry posts the residual to the separate advance-liability account.
- In On Receipt mode, `Donation.amount` is the intended amount, not an
  outstanding receivable. Recognized/received/refunded totals are derived from
  submitted linked accounting vouchers. Underpayment leaves no fictitious debt;
  excess over intent stays as unallocated Customer credit until an authorized
  operator explicitly accepts it as an increased
  gift or refunds it. Only the accepted amount is invoiced and recognized; the
  callback never recognizes excess before that decision. In Receivable on Submit
  mode, the invoice amount is the fixed recognized pledge and standard
  outstanding remains due.
- Later excess acceptance creates a locked child `Donation Accounting Event` with
  `event_kind = "Excess Acceptance"`, parent event, unique decision key, accepted
  amount, and its own unique Sales Invoice event key. It allocates only the
  still-unallocated credit from the original Payment Entry through standard
  reconciliation. The parent/child event totals and source Payment Entry are
  re-read under lock so retries cannot recognize the same residual twice.
- A gateway intent remains non-ledger until confirmation. Use a supported
  non-ledger checkout reference such as Sales Order when the provider supports
  it, or a reviewed Donation transport adapter whose callback invokes the same
  invoice-and-payment service. Never create an unpaid Sales Invoice merely to
  obtain a checkout URL for a revocable gift.
- Automated bank settlement uses a two-stage ownership contract. Candidate
  providers remain side-effect-free and Good Connector retains aggregate
  ambiguity handling and selected-target locking. Before candidate work, a
  non_profit transaction-gate hook derives Company from the Bank Transaction/
  account, then acquires uncached identity, donation-accounting, and that Company
  Donation Accounting Configuration permits in global order and retains them
  through commit. Good Connector reads candidates without holding Bank Transaction,
  then locks selected Donation before Bank Transaction and reruns candidate/
  eligibility checks under both locks, replacing its current Bank-Transaction-
  first order. The transactional materializer hook then creates/submits the
  event-keyed Sales Invoice and returns the unsaved standard Payment Entry;
  Good Connector validates/submits that Payment Entry and links the Bank
  Transaction in the same database transaction. No layer commits internally, so
  any invoice, payment, or bank-link failure triggers a full transaction rollback,
  not merely Good Connector's current savepoint rollback. The worker then records
  Review/Error only in a fresh status-only transaction that reacquires all three
  permits, Donation, and Bank Transaction and conditionally updates the same operation/
  source state; a concurrent successful retry makes the stale failure write a
  no-op/superseded audit rather than overwrite reconciliation. This boundary must clear
  after-commit/rollback callback managers and buffered realtime/webhook work so a
  rolled-back invoice or payment emits no side effect when status later commits.
  Events needing excess/identity review remain unmatched and create no invoice.
- Rollback is not assumed to retract synchronous external side effects. All
  non_profit-owned NPO voucher hooks write only transactional records or an
  `NPO Accounting Outbox`; unique internal event creation occurs in the business
  transaction and delivery starts after successful commit. Workers claim rows
  with expiring lease tokens and retry with the stable event key. External
  delivery is explicitly at-least-once; receivers that support an idempotency key
  must use that event key for effectively-once acceptance, while email/Slack
  channels without such support may duplicate after an ambiguous crash.
  Activation inventories enabled Notification, Webhook, Server Script, and
  installed `doc_events` for the complete declared atomic-flow DocType set,
  including at least Donation, Payment Intent, Economic Receipt/Source/Event,
  Membership Ask and its Economic Receipt/Source, Refund Instruction/Source,
  Credit Application, Sales Invoice, Payment Entry, Journal Entry, Bank
  Transaction, Donation Receipt/Claim, and Process Reconciliation records.
  Any synchronous email/Slack/HTTP or unknown side effect must explicitly exclude
  NPO financial purposes or declare/test an outbox-safe capability. Persist this
  automation-policy hash with the capability manifest; config hooks and each
  gated writer fail/suspend on drift. Unsafe automation blocks activation rather
  than relying on transaction callback cleanup.
- Every Posted On Receipt event fences its Sales Invoice and accepted Payment
  Entry allocation even before a Donation Receipt exists. Ordinary cancellation,
  update-after-submit, Payment Reconciliation, Unreconcile Payment, or
  reallocation is rejected. A controlled event Void/Reattribute operation locks
  the event/vouchers, reverses or reallocates them atomically with immutable audit
  and a new event attempt; a real gift refund follows the refund lifecycle. If a
  receipt claim exists, its correction/release must complete first.
- Every Receivable-on-Submit pledge invoice is likewise service-owned and fenced.
  Direct cancellation/amendment/unreconciliation is blocked. A controlled
  clerical Void/Reissue operation marks the old event attempt void and issues a
  new unique attempt; legal pledge release/reduction follows the Credit Note
  lifecycle below, so the submitted Donation and pledge event key cannot be left
  stranded by an ad hoc invoice cancellation.
- A mixed On Receipt Payment Entry carries a maintained donation-fund disposition
  for any unallocated excess: `Excess Pending`, `Excess Accepted`, `Excess
  Released`, or `Excess Refunded`. Payment Reconciliation and Sales Invoice
  automatic-advance discovery exclude Excess Pending. An operator must accept,
  refund, or explicitly release it to general Customer credit through an audited
  locked operation before unrelated reconciliation may consume it. Release is
  forbidden for the pooled Anonymous System Customer, whose excess remains bound
  to the same Economic Receipt until accepted or refunded.
- Customer-model V1 prohibits ordinary Journal Entry settlement/write-off
  references against Donation or Donation Reversal Sales Invoices. Typed
  exceptions are only the service-owned Holding Capture/Reclassification/Refund
  lifecycle and NPO Credit Application for an explicitly Released standalone
  Credit Note. Reclassification may settle only its exact Donation invoice from
  the same Economic Receipt; Credit Application has the exact two-row matrix in
  section 7.4. Guards cover Journal Entry validate/update-after-submit, Payment
  Reconciliation, and unreconciliation so no untyped JE changes outstanding or
  receipt eligibility.
- Refunds and chargebacks follow the shared Refund Instruction matrix: accepted
  income uses the exact Credit Note/outgoing Payment Entry mode, unaccepted excess
  uses reverse Payment Entry reconciliation, held funds use Holding Refund JE,
  and an enforceable chargeback reverses payment allocation without inventing a
  Credit Note. No path erases a real receipt by cancelling original Donation
  accounting vouchers.

The Good NPO/Good Connector Swiss adapter gives Donation QRR one active owner.
`Receivable on Submit` assigns QRR only
to the Donation Sales Invoice; Donation/Intent expose no competing candidate.
`On Receipt` assigns QRR only to the non-ledger Donation. Payment Intents never
own/copy an active QRR or appear as QRR candidates; provider callbacks resolve
them by provider/source identity. Generated immediately settled Sales Invoices
remain QRR-empty. Under the Donation lock, QRR stays active only while the
Donation is open and cumulative gross accepted events are below intended amount;
it becomes inactive atomically when funded or through controlled close/cancel/
amend/continuation handoff. Void/refund never reactivates an old QRR automatically,
a continuation receives a new QRR, and observations against an inactive
historical QRR enter review. At cutover a legacy QRR is historical/inactive unless
moved under lock to the one active continuation.
Good Connector's Company-locked registry/collision scan covers active Donation,
Donation pledge Sales Invoice, Membership Ask, Membership Sales
Invoice, and legacy identities according to these ownership rules.

The current direct `Payment Entry -> Donation` path remains only for persisted
`Legacy Donor Direct` rows. Its existing hook-based company, account, locking,
allocation-total, paid-state, and reconciliation checks remain, and are
strengthened to require submitted Donation plus exact
`Payment Entry.party == Donation.donor`. Customer Invoice rows reject direct
Donation references. After cutover, legacy hooks permit only correction,
unreconciliation, or reversal of existing exact references and reject every new
direct allocation. Base reporting/outstanding/analytics dispatch from the
immutable accounting model, while Payrexx and Good Connector dispatch their
payment/refund and EBICS/QRR transport from that same model:
legacy rows use the preserved custom settlement interpretation; new rows use
Sales Invoice and Payment Ledger state.

Donation Receipt qualification facts are based on actual allocations, not merely
the Donation's intended amount or a mutable paid flag. Each receipt item freezes
typed source model, Donation, optional Sales Invoice, Payment Entry/allocation or
reviewed legacy evidence, received amount, payment date, and recognition Donor.
The receipt header freezes one recipient Customer/name/address/language plus
selected jurisdiction, provider/policy version, template key/version, and legal
decision; mixed-recipient items are rejected. Source types are `Customer Invoice
Allocation`, `Donation Holding Reclassification`, `Legacy Donor Payment Reference`,
and `Reviewed Legacy Manual Evidence`; Customer and Holding sources require the
exact Donation Sales Invoice/Economic Receipt chain.

Jurisdiction is selectable on the draft/generation request and may default from a
presentation app, but it is never hardcoded by `non_profit`. Any Country may be
stored for forward compatibility. Submission resolves a matching versioned receipt
policy provider; absence, unsupported language, or stale provider/template blocks
issue/send while accounting remains available. Jurisdiction/provider/policy are
immutable after submit, and every correction inherits them from the original.
V1 ships only the Switzerland provider from `good_npo`.

Each eligible source has a deterministic canonical allocation key. A normal
`Donation Receipt Allocation Claim` uses that key as its unique document identity
and stores the current submitted receipt plus immutable claim/release history.
Receipt submission follows IR-12: accounting control, Donation/lineage, source
voucher/evidence, then claim in deterministic order; cancellation uses the same
order and releases the current claim without erasing
history, allowing an audited replacement. Thus one eligible allocation appears
on at most one current submitted receipt, while one Donation may contribute to
multiple fiscal-period receipts after partial payments. Receipt recipient remains
an explicit legal/business choice separate from payer and observed remitter.

An active submitted receipt claim fences its source allocation. Payment Entry
cancel/update-after-submit, Payment Reconciliation, Unreconcile Payment, Sales
Invoice cancel/return, and any reallocation must either leave the claimed amount
unchanged or run the controlled refund/correction flow. That flow locks the
accounting control, Donation/lineage, source, then claim in IR-12 order, obtains the
snapshotted provider decision, and submits the refund accounting voucher,
immutable correction, claim disposition, and correction-series number in one
database transaction under one refund idempotency key. Delivery is inserted once
into the Accounting Outbox and starts only after commit. Rollback leaves no
correction or email; refund undo atomically creates the reversing correction.
Direct mutation that would make a submitted receipt false is rejected.

Base qualification facts report source allocation amount/date, net retained cash,
Donation-purpose income recognition, held/released/refunded amounts, and prior
corrections without declaring a legal cap. The provider decides legal entitlement,
issuable amount, fiscal period, recipient, and document kind; base only verifies
that the returned allocation does not exceed or duplicate immutable source facts.
Receipt creation and Credit Note submission lock the same event/claims and either
update unclaimed facts or require the provider-selected correction for an already
submitted receipt.

### 8.1 Donation cancellation, amendment, and refund lifecycle

- Donation cancellation locks Donation plus every Payment Intent, Economic
  Receipt, source observation, Accounting Event, voucher, and receipt claim. It
  is allowed only when there is no accounting/receipt and every intent/observation
  is Expired or provider-confirmed Revoked. Pending, Authorized, Captured/Held,
  imported-but-unresolved, or concurrently confirming funds block cancellation.
  Once real accounting or a receipt exists, cancellation is not an erasure
  mechanism.
- A capture reported after revocation/cancellation is never dropped or posted to
  a cancelled Donation. It creates/updates the Economic Receipt and moves the
  Intent to provider Captured with Held accounting disposition, then posts the unique Holding
  Capture voucher so provider asset and refundable liability are recognized
  without income. A controlled operation either reattributes it to an active
  successor Donation and uses Holding Reclassification once, or submits Holding
  Refund. Amendment likewise
  transfers only a non-captured intent under both Donation locks; captured funds
  remain with the original event until reattributed/refunded.
- For `Receivable on Submit`, a payment chargeback/reversal while the pledge
  remains enforceable uses the uniquely instructed, source-dated chargeback Pay
  voucher plus reverse-payment reconciliation so the original Sales Invoice
  becomes outstanding again; it does not create a Credit Note. A
  genuine pledge reduction/release follows the applied-versus-standalone Credit
  Note split matrix, with outgoing Payment Entry only for an instructed refundable
  paid portion.
- For `On Receipt`, accepted funds remain historical. A real refund/chargeback
  that extinguishes the gift uses the shared accepted-refund or accepted-
  chargeback matrix against the Donation-linked invoice; an outgoing Payment Entry
  exists only when cash has not already been removed. Unaccepted excess is
  refunded from standard unallocated Customer credit without reversing donation
  income that was never recognized. The outgoing refund explicitly references or
  standard-reconciles against the original incoming Payment Entry's receivable
  credit; it must not resolve to the separate advance-liability account merely
  because that Company setting is enabled.
- Original Donation links and event keys are `no_copy` onto Credit Notes.
  `return_against` plus a non-unique reversal link preserve traceability, and the
  Credit Note sets `npo_financial_purpose = "Donation Reversal"`.
- An amended Donation inherits subject, Customer, accounting model, and timing,
  but the original Donation retains every historical invoice, payment, refund,
  and receipt. Future events use the amendment's own namespaced keys; accounting
  changes to the original use standard Credit Notes/new charge invoices rather
  than moving vouchers between Donations.
- A refund before receipt updates the allocation's retained/refunded facts for the
  jurisdiction provider and needs no correction because no document was issued. A
  refund after a submitted receipt creates a generic immutable correction request linked to the
  original receipt/allocation. The snapshotted jurisdiction provider selects the
  required correction/reversal document and delivery disposition. Refund voucher,
  correction, and claim update commit atomically; automatic delivery starts after
  commit. Refund cancellation atomically creates the provider-selected reversing
  correction. Issued receipt evidence is never silently edited; `non_profit`
  defines no country-specific correction format or wording.

### 8.2 Donation regime backfill and cutover

Customer accounting is activated per site, never merely by installing code. A
fixed row named `donation-accounting` in the normal (non-Single), tightly
permissioned `NPO Party Model Activation` DocType stores its state, active/target
version, approved migration run, schema/index and installed-capability manifest
hashes, operation ID, fence time,
checkpoints, activation time/operator, and last error. Every Donation insert
and every Donation-affecting writer acquires an uncached shared database lock on
this row through commit: Donation/Recurring Donation, Payment Intent callback,
Sales Invoice/Payment Entry/Journal Entry mutation, Payrexx, Good Connector/EBICS
materialization, Payment Reconciliation/unreconciliation, refund/Credit Note,
receipt claim/correction, and reporting-state rebuild that writes derived totals.
The activator takes the same stable primary-key row exclusively, so all
pre-boundary writers drain before Active and no Compatibility writer can commit
after the cutover boundary.

It uses explicit backfill `Compatibility -> Backfill Fenced -> Compatibility`,
activation `Compatibility -> Fenced -> Installing Indexes -> Verifying -> Active`,
and maintenance `Active -> Fenced -> Installing Indexes -> Verifying -> Active`
graphs, plus Recovery Required and Suspended. Compatibility inserts Legacy Donor
Direct; Active inserts Customer Invoice; every backfill/transitional, recovery, or
suspended state rejects ordinary Donations and model-changing accounting
operations. Only the matching migration operation writes during Backfill Fenced.
Activation commits the fence, waits for earlier writers, reruns the accounting
fingerprint, then commits Active. No creation-time comparison or cached setting
decides the model.

Before activation:

- Every existing Donation in every docstatus, including drafts, submitted,
  partly allocated, manually paid, cancelled, amended, receipt-linked, and
  recurring-generated rows, is backfilled to
  `accounting_model = "Legacy Donor Direct"`, `accounting_party_type = "Donor"`,
  and `accounting_party = donor`.
- `Donation.customer` may be populated for identity/navigation, but it does not
  change the immutable legacy accounting party.
- Any Donation with missing Donor, mixed party references, or contradictory
  accounting history is a blocking remediation issue.
- The audit includes Payment Entry, Journal Entry, GL Entry, Payment Ledger
  Entry, Party Account, opening balances, Bank Transaction links,
  reconciliation/unreconciliation records, Donation Receipt, manual paid state,
  and any other Dynamic Link or reference to Member/Donor Party Type.
- Existing submitted Donation Receipts keep immutable legacy items and their
  historical print renderer. Backfill a typed allocation key only when the exact
  submitted Payment Entry reference is provable. A manually paid row or ambiguous
  amount requires a restricted Reviewed Legacy Manual Evidence record; migration
  never invents an allocation. Refund/cancellation state is part of eligibility.
- Keep `Donation.receipt` as read-only legacy navigation while old receipts exist;
  new one-to-many receipt lookup uses items/claims. Retire the old field only
  after every supported site's submitted receipts are classified and historical
  rendering/regeneration is verified.
- Source and backfilled counts plus a hash/fingerprint are persisted in the
  migration run. The operation is resumable and idempotent.
- Classify each legacy row as `Historical Accounting`, `Unledgered Convertible`,
  or `Close Without Future Accounting`. For Historical Accounting, audit whether
  the direct Payment Entry path recognized valid income and require an explicit
  accounting remediation decision; migration never fabricates GL entries.
- Under the final write fence, convert only approved unledgered rows to Customer
  Invoice with resolved subject/Customer/timing. Cancel/close the other unledgered
  rows. A legacy row with submitted/partial accounting remains historical and
  never converts its existing vouchers.
- Under the same fence, disposition every adopted non-terminal Payment Intent and
  unresolved source observation: bind it to the converted Customer-model row or
  approved continuation, provider-confirm and record Revoked/Expired, or create
  the Economic Receipt/Holding Capture for already captured funds. A Historical
  Legacy Donation cannot remain the future callback target. Callback lookup uses
  provider Intent identity first before/during/after activation.
- Inventory every historical/manual/provider refund and chargeback identifier,
  Credit Note, outgoing Payment Entry, and Holding-like Journal Entry. Provable
  tranches are adopted into immutable NPO Refund Instruction/Source rows with
  their existing voucher links and terminal state; ambiguous mappings are
  blocking issues. A replay-capable provider event may not be declared terminal
  without provider evidence that callbacks are revoked/expired and cannot recur.
  Every callback-visible refund/source key must resolve to an adopted instruction,
  a fenced continuation, or an explicit holding/review disposition before Active.

Partly funded legacy rows use explicit lineage rather than an unrelated new gift.
Donation gains immutable `lineage_root`, `predecessor_donation`,
`continuation_sequence`, `continuation_reason`, and cutover-snapshotted
`remaining_intent`. A nullable active-lineage key is database-unique; creation
locks the root and permits at most one current Customer-model continuation. Its
amount is the reviewed remainder after valid legacy allocations, never the full
original intent. The old QRR becomes historical/inactive and future matching
routes only to the continuation's new reference. Fundraising/reporting counts the
root intent once while aggregating legacy and continuation receipts/payments;
receipt recognition retains each typed source without double-counting.

Activation then establishes this deterministic boundary:

- Pre-existing Historical Accounting Donations remain Legacy Donor Direct for
  interpretation, correction, reversal, and receipt history. After activation,
  no new Payment Entry allocation may reference one directly. A partly funded
  legacy row needing future funds uses a separately linked Customer-model
  continuation Donation under this lineage contract rather than extending
  malformed accounting.
- Approved Unledgered Convertible rows use Customer Invoice after the fenced
  conversion. Any old draft left Legacy Donor Direct cannot submit or receive
  accounting after activation.
- A Donation inserted after activation stores `accounting_model = "Customer
  Invoice"` and holds the lock for its represented
  subject: canonical Person Contact, organization Customer, Household, or fixed
  Anonymous System key. It
  resolves/creates the matching Customer and snapshots the Customer Invoice model
  on insert. It cannot be saved as a Customer-model Donation with unresolved or
  ambiguous identity.
- Customer-model amendments inherit model and exact accounting party. A legacy
  amendment is correction-only and cannot accept new funds; future activity uses
  a linked Customer-model continuation so accounting models never mix.
- New installments from a Recurring Donation use the model active when each
  Donation is inserted; the generated Donation stores the immutable result.
- Cancellation never clears model fields. Reopening or editing a draft cannot
  change a model after any accounting reference exists.
- Payrexx, EBICS/QRR, manual Payment Entry, reconciliation, reporting, receipt,
  analytics, and outstanding paths dispatch from the stored model, never from
  creation date or the Donor's current Customer. Customer Invoice paths create or
  settle Donation-linked Sales Invoices; they never add Donation as a direct
  Customer Payment Entry reference.

The legacy regime can be omitted on a site only when the complete audit proves
that no persisted Donation or accounting history requires it. Absence of Donor
Payment Entries alone is insufficient. A development site may choose an
explicit destructive reset only after export; migrate never infers that choice.
After the first Customer Invoice Donation exists, behavioral rollback to Legacy
Donor Direct is prohibited. Emergency suspension fences new Donation accounting;
actual rollback requires an offline site restore or a separately reviewed forward
data migration that preserves post-cutover vouchers.

Member should no longer be installed as an accounting Party Type because current
membership accounting already uses Customer. Donor Party Type remains while any
supported accounting row uses the legacy Donor regime; it stops being installed
for new use only after Customer-based posting is complete. Existing Party Type
records must remain when Payment Entry, Journal Entry, GL Entry, Payment Ledger
Entry, or opening-balance history still resolves through them.

## 9. Consolidation And Split Operations

Raw ERPNext merge is not the orchestration layer for constituent identity.
Frappe merge broadly rewrites incoming Link and Dynamic Link values and deletes
the source record. It does not decide how to reconcile Customer child rows,
primary Contacts and Addresses, portal users, duplicate Member/Donor roles,
external IDs, or accounting history.

### 9.1 Household separation

Household separation first changes dated Household Person relationships. Person
Contacts and Individual financial identities remain unchanged. If the old
Household has a Customer, Donor, Bank Account, ask, or accounting history, apply
the financial preservation rules in section 7.6: retain the historical joint
financial identities, block new-period activity at the separation effective
date, resolve open items through controlled settlement, allow eligible historical
receipt/correction operations, and create new projections only for future
activity.

### 9.2 Duplicate consolidation

Use when two records represent the same real person or organization:

1. Select the canonical Contact or NPO Organization. Separately decide whether
   organization Customers are true duplicate accounting masters or intentional
   operating units.
2. Inventory every dependent record before mutation.
3. Reconcile Contact emails/phones, Addresses, Dynamic Links, portal users,
   external source IDs, primary pointers, and role records explicitly.
4. Consolidate Memberships only after checking date/type overlap.
5. Consolidate Donor relationships only after inventorying Donations, Recurring
   Donations, Donation Receipts, Major Gifts, Donor Interactions, Household
   history, analytics scores, and segment membership.
6. Preserve source identifiers through an alias/audit record.
7. Send every ambiguous conflict to manual review.

An accounting party without submitted ledger history may use ERPNext merge only
after its child rows and role conflicts have been reconciled. An accounting
party with submitted history normally remains linked to the canonical party as a
Settlement Only Alias until open/correctable dependencies are resolved, then as
an Archived Alias. It is blocked for unrelated new activity but retained for
historical documents. Do not rewrite submitted GL or Payment Ledger party
identity merely to make the master list look deduplicated.

Archived aliases require an explicit identity status and canonical-record link.
Only the active canonical record carries the unique canonical Contact or active
role constraint. A Settlement Only accounting alias (Customer, Supplier, or
legacy Member/Donor Party Type) retains the minimum links needed for exact-party
historical settlement/correction but cannot receive unrelated transactions or
role activity. A finalized archived Customer, Supplier, Member, Donor, or
Volunteer alias is excluded from active uniqueness checks and normal selectors.
The concrete fields and lifecycle are defined in IR-11; this section does not
imply an unmodeled status flag.

### 9.3 Identity split

Use when one record incorrectly represents two real people or organizations:

1. Create the missing Contact, NPO Organization, role, Customer, or Supplier
   records.
2. Move only relationships whose ownership is supported by explicit evidence.
3. Move future and unsubmitted activity to the correct identity.
4. Leave submitted financial documents on their historical party unless a
   separately approved accounting correction is required.
5. Record the operation and effective date so reports can explain the boundary.

Implement consolidation and split through a controlled service or review
DocType with preview, deterministic locking, dependency counts, explicit
operator confirmation, and a durable audit result. Do not expose a one-click
automatic merge based on email or name.

## 10. Implementation Plan

### Phase 0: Business decisions

Resolve the decision gates in section 11. Proposal acceptance does not activate
them. Add stable requirement IDs, target releases, app owners, migration
versions, and rollback boundaries before modifying DocTypes.

### Phase 1: Read-only identity audit

Build a report that identifies:

- Duplicate or source-preserved Contacts that may represent one person.
- Person-like, generic-endpoint, and unclassifiable Contacts, including Contacts
  whose current roles disagree about identity kind.
- Contacts linked as the identity anchor of multiple Person Customers.
- Core Individual Customers with no explicit NPO subject classification, or a
  Person classification without a stable identity Contact.
- Individual Member or Donor roles without an unambiguous Contact.
- Organization Member or Donor roles without an organization Customer.
- Multiple Individual Members or Donors for one canonical Contact.
- Multiple Organization Members or Donors for one Customer.
- Member and Donor records that appear to represent the same person but use
  different Contacts or Person Customers.
- Volunteers without Contact or with duplicated email identity.
- Every Contact and Address Dynamic Link to Member, Donor, Volunteer, Household,
  Customer, and Supplier, including links that disagree with proposed direct
  canonical fields and role-only Addresses needing relocation.
- Every Payment Entry, Journal Entry, GL Entry, Payment Ledger Entry, and
  opening-balance row using Member or Donor Party Type, including open or partly
  paid Donations, on every deployed site.
- Every persisted or externally pending Donation checkout/provider transaction,
  including Payrexx-related Integration Requests, provider IDs/status, Payment
  Requests, callbacks, captures, refunds, chargebacks, and unresolved webhook
  payload references. Provider export/dashboard reconciliation is a blocking
  preflight where local state cannot prove terminal status.
- Per-Company membership advance and donation accounting configuration: separate
  advance-liability setting/account, receivable and clearing accounts, donation
  Item/income/tax policy, currency, dimensions, and any incompatible historical
  account use.
- Customer/Supplier pairs that likely represent the same entity but lack Party
  Link.
- Existing one-to-many, reverse, or type-incompatible Party Links.
- Individual Suppliers without a canonical Contact or with a Contact already
  assigned to another active Individual Supplier.
- MiKi Members that do not resolve to exactly one organization Customer, and
  Customers linked to multiple MiKi-eligible Members.
- MiKi parent/child Customer hierarchies, child-specific Members, and existing
  declaration-item relationships that consolidation must preserve.
- Installed Customer/Supplier Type Property Setters that remove ERPNext's
  Partnership option, including MiKi's current global setters.
- Household, Household Person/Member, `Customer.household`, and
  Contact-to-Household Dynamic Link counts on every deployed site. The clean
  replacement may proceed only when this preflight proves no production use.
- Every inferred household Membership, its possible Household, current people,
  payer evidence, and whether an approved source can prove covered Members.
- Every potential Household financial identity: joint Customer/accounting rows,
  joint Donor/receipt attribution, Membership payer choice, joint Bank Account,
  open ask, advance, credit, invoice, and payment. Shared name/address/IBAN alone
  remains review evidence, not automatic conversion authority.
- Existing disabled Customers/Suppliers and any informal Member/Donor aliases
  that require explicit status and canonical links.
- Claimed versus verified organization UIDs, duplicate normalized UIDs,
  parent/child operating Customers that share a claim, organizations without
  reliable identifiers, and Supplier-only organizations that must not be forced
  into Customer.
- Every current helper/API caller, including external dotted paths, gateway
  callbacks, imports, reports, permission hooks, and scheduled jobs.
- Every receipt country value and whether it was explicit or inherited from the
  current Switzerland default; historical renderer/template hash and language;
  `Donation Receipt DE`, `Donation Slip CH`, `Donation Thank You DE`, Swiss QR
  renderer, stored QRR/QR-IBAN evidence, and Swiss UID source/provider provenance.
  A metadata default alone does not prove legal jurisdiction.

The audit must not merge or mutate records automatically. It persists one
fingerprinted result per site and model version so enforcement cannot rely on a
transient report or an assertion that another environment was empty.

### Phase 2: Introduce the target schema

- Add nullable subject type, direct Contact, identity status, and canonical-alias
  fields to Member and Donor, including the unique nullable Anonymous System key.
- Add Contact identity kind plus nullable Customer/Supplier canonical Contact,
  Customer/Supplier NPO-managed markers, Customer subject type,
  Person/Household/Organization/system anchors, identity status, and
  canonical-alias fields through `non_profit` setup.
- Add `Contact Email.npo_endpoint_kind` (`Personal`, `Shared`, `Unknown`) and
  verification metadata; only a verified Personal endpoint unique across active
  Person Contacts may prove an unauthenticated person claim.
- Add normal `NPO Verified Identity Endpoint` with immutable value snapshots,
  nullable unique active key, verification/revocation/transfer history, and claim
  invalidation links; Contact Email fields are managed projections of this
  registry, not the uniqueness authority.
- Add `NPO Organization` and standalone `NPO Organization Verified Key`, plus
  Projection Approval and immutable Identity Action records, plus service-owned
  Customer/Supplier organization links. Do not copy MiKi-owned UID/legal-form
  fields or enforce uniqueness directly on an operating Customer.
- Add Donor Household subject anchor alongside Individual Contact and
  Organization Customer subject fields.
- Add Donation Receipt recipient Customer and address snapshots so joint or
  third-party payer history does not change when master data changes.
- Add Dynamic Link identity-projection provenance fields through `non_profit`
  without replacing app-specific relationship-role metadata.
- Add nullable Volunteer Contact and alias fields without renaming existing rows
  yet; record the old name/email mapping needed for the controlled rename phase.
- Add Household Person, dated Household Address Link, financial closure, and
  correspondence-default fields alongside the old Household Member/Dynamic Link
  model. Do not remove or reset old rows in schema introduction.
- Add Membership scope, Household, payer scope, optional billing Member, billing
  Customer, covered-Member schema, immutable cycle namespace, Membership Type
  collection mode plus effective policy version/history, and Membership Ask
  alongside the compatibility flag. Existing null collection modes remain
  blocking review rather than receiving a schema default.
- Add NPO-managed Membership ownership/policy version to Subscription and immutable
  billing-cycle input snapshot/fingerprint fields to the original Membership
  Subscription Sales Invoice. Register managed Subscription scalars and its
  Subscription Plan Detail children in the protected lifecycle before generation.
- Add immutable `Membership Ask Economic Receipt`, globally unique Receipt Source
  aliases, and deterministic Receipt Observation Lock; include source/value/
  reviewed posting dates and override evidence. Every Ask-owned incoming Payment
  Entry attempt links one Receipt, and receipt/source status has no editable GL
  totals.
- Add indexed `Payment Entry.membership_ask`, maintained Membership Ask and
  Donation excess fund dispositions, and unique
  `Sales Invoice.membership_ask` links as the ERPNext-only settlement/advance
  contract. Mark the unique original-invoice link `no_copy` and add a separate
  non-unique reversal/audit link; optional QRR/EBICS fields remain owned by their
  existing integrations.
- Add immutable `Payment Entry.npo_membership_billing_cycle_key` for focused
  Individual/Organization Membership Subscription settlement; it is empty for Ask,
  Donation, and ordinary Payment Entries and cannot authorize another cycle.
- Add read-only skipped/reason fields to Process Payment Reconciliation Log
  Allocations plus skipped-count/`requires_rerun` and
  `npo_contains_protected_allocations` fields to Process Payment Reconciliation
  and its Log for the pre-job stale-disposition sanitizer; they are audit/coarse
  fence only, not a replacement ledger or substitute for row-level owner checks.
- Add the proposed Donation Customer, accounting model/timing/party fields,
  lineage/continuation fields including root `lineage_intended_amount`, immutable accounting namespace and Donation event-
  root/attempt keys, Donation-linked
  Sales Invoice attempt keys, and allocation-based Donation Receipt
  fields plus `Donation Receipt Allocation Claim` and generic correction links
  without changing posting behavior yet. Receipt header fields include selectable
  jurisdiction Country/code, provider/policy version, language, template key/
  version, one recipient snapshot, legal decision, and correction lineage; items
  carry only qualification-source facts. Donation/original-event fields are
  `no_copy` onto returns. `non_profit` adds no Swiss default, template, UID policy,
  QRR, or QR-bill field/fixture.
- Add the permission-aware versioned fundraising-fact read model/materializer with
  one row per lineage root, exact source fingerprint/formula version, and no
  independent editable accounting values.
- Add normal `Donation Economic Receipt`, globally unique `Donation Economic
  Receipt Source` aliases, deterministic `Donation Receipt Observation Lock`,
  provider-neutral `Donation Payment Intent`, and `Donation Accounting Event` for cross-source deduplication and
  manual/external receipt idempotency,
  status, source/payment/posting dates, Company-currency provenance,
  accepted/excess/refunded amount, source provenance, parent excess decision, and
  voucher links; it is not a parallel ledger and contains no editable accounting
  totals after posting.
- Add shared immutable `NPO Refund Instruction` and globally unique `NPO Refund
  Source` aliases, plus unique service-owned instruction links on Credit Note,
  outgoing/recovery Payment Entry, forward recovery Sales Invoice, and Holding
  Refund Journal Entry. Include source/economic/cash/recognition dates, closed-
  period override reasons, tranche amount, voucher mode, and parity status.
  Membership and Donation refund paths must adopt an instruction before any
  voucher is created.
- Add immutable `NPO Credit Application` with unique application key, Refund
  Instruction/source Credit Note/target invoice/amount/date/dimensions, and unique
  purpose-marked Journal Entry link. It is the only retained-credit consumption
  path and carries no editable accounting totals.
- Add base-owned `Sales Invoice.npo_financial_purpose` (`Donation`, `Membership
  Ask`, `Membership Subscription`, `Donation Reversal`, `Membership Ask Reversal`,
  `Membership Subscription Reversal`, `Donation Refund Recovery`, `Membership Ask
  Refund Recovery`, `Membership Subscription Refund Recovery`, or empty) so installed
  vertical apps can route/exclude these standard invoices without guessing from
  Items or Customer. Controlled return mapping assigns the matching reversal
  purpose explicitly. Recovery invoices use a unique Refund Reversal Instruction
  link and never consume any original Donation/Ask/Membership-cycle unique owner
  link.
  Add base-owned `npo_membership`, optional `npo_subscription`, immutable billing-
  cycle/attempt keys, and non-unique reversal audit links; Good NPO's existing
  field is a compatibility mirror maintained from these canonical owners.
- Treat NPO financial purpose and all owning/reversal links as read-only,
  service-owned, and immutable after submit. Validate a strict matrix: Donation
  requires only a Donation charge link; Membership Ask requires only its original
  Ask link; Membership Subscription requires one Membership and unique billing-
  cycle/attempt key. Subscription Cycle additionally requires matching
  `npo_subscription = subscription` plus exact native `from_date`/`to_date`, while
  Direct Membership Cycle requires all native Subscription fields empty. Each Reversal requires
  `is_return`, `return_against` the matching NPO
  purpose, and its non-unique owning reversal link; each Refund Recovery requires
  `is_return = 0`, one unique reversal instruction, and the matching original
  Credit Note, while Donation/Ask/Membership/Subscription original-owner links,
  unique billing-cycle/attempt keys, and native `subscription`/period fields remain
  empty. Empty purpose forbids those links. Forging, clearing, copying, or cross-linking is rejected in
  server hooks and focused-write services.
- Add service-owned `Journal Entry.npo_financial_purpose` (Donation Holding
  Capture/Reclassification/Refund, Membership Credit Application, or Donation
  Credit Application) and exact source/application links.
  The strict purpose/link/account matrix is immutable after submit and ordinary
  Journal Entries cannot set these fields.
- Add immutable `NPO Party Link Approval` plus Party Link audit/reporting before
  enabling strict one-to-one validation; it is separate from organization
  projection approval.
- Add restricted expiring `NPO Identity Claim` for public proof-of-control,
  opaque candidate handling, one-time token state, and reviewed resolution; it
  stores no credentials and cannot itself anchor a role or accounting document.
- Add restricted `NPO Privacy Request` plus protection-domain/source/purpose
  fields for File, Communication, Comment, Notification Log, Email Queue, and
  related links. Generic personal-data hooks, artifact permissions, private-file
  migration, and timeline fan-out guards exist before canonical PII activation.
- `non_profit` introduces `NPO Identity Migration Run` plus flat
  `NPO Identity Migration Issue` records linked to the run, so large migrations
  do not store thousands of issues in one child table. They contain model
  version, phase status, source/target counts, fingerprints, restart cursor,
  operator decisions, and activation flags. Both DocTypes have real Python
  controllers and explicit restricted permissions.
- Add immutable restricted `NPO Protected Change Audit` and service-owned
  protection-domain/source/audit fields on core Deleted Document. Protected
  `save_version`, the `DeletedDocument.db_insert` snapshot interceptor, direct Version/Deleted Document
  permissions, and restore overrides are installed before migration exposes the
  new canonical fields.
- Add immutable restricted `NPO Ledger Repost Run` with range/voucher/source/
  ledger fingerprints, operation/fence state, and verification result; protected
  ERPNext repost workers require it.
- Add restricted retention-managed `NPO Protected Diagnostic`; protected jobs and
  core Error/RQ/Scheduled logs retain only its opaque incident ID and generic code,
  never raw protected arguments or traceback.
- Declare required deployment hooks `party_model_epoch_provider` and
  `protected_payload_key_provider`, plus the external erasure-journal capability.
  Store only provider IDs/versions, public verification metadata, key IDs, and
  hashes in site data; no signing/KEK material or external monotonic state enters
  ordinary backups. Their effective paths/protocol versions are capability-
  manifest inputs.
- Declare the mandatory `party_model_backup_restore_shim`, external backup-
  generation manifest protocol, restore-quarantine/promotion receipt, and startup
  gate, runtime-generation lease/fencing protocol, and default-deny successor-
  export schema. Disable direct core scheduled/live-site backup/restore paths in
  strict deployment; shim/protocol versions, redaction schema hash, and scheduler/
  entrypoint hashes are capability inputs.
- Add normal DocType `NPO Party Model Activation` with deterministic `identity`
  and `donation-accounting` rows. It is deliberately not a Single DocType: each
  row must provide a stable primary-key mutex across normal writes and DDL
  checkpoints. Store state, active/target version, approved migration run,
  schema/index manifest hash, installed-capability manifest hash, operation ID,
  monotonic site/model epoch and external-anchor hash, fence/DDL/activation
  timestamps, last verified step, operator, and error. Raw activation and migration issue/evidence records
  are restricted to System Manager and the applicable Accounts authority;
  Non Profit staff use a separate permission-aware redacted report.
- Identity and donation controls both recognize service-owned `Backfill Fenced`
  in addition to Compatibility, activation/maintenance states, Recovery Required,
  and Suspended. Only the matching migration operation may write in Backfill
  Fenced; ordinary writers and callbacks fail closed.
- A versioned one-time introduction patch, recorded in Patch Log, creates both
  control rows in Compatibility on the first upgrade of an existing populated
  site and records `introduced_from_legacy`, source fingerprint, app/model
  version, and timestamp. This explicit bootstrap is distinct from later row
  loss; rerunning setup cannot reproduce it after the patch marker/evidence exists.
- Activation rows are service-owned fixed control records: controllers block
  rename, trash, discard, ordinary form/import edits, unknown transitions, and
  operation-ID mismatch. The protected-DocType `insert`/`_save` guards reject a
  forged `_action = "discard"` before Frappe can skip those controller validations.
  Missing/corrupt rows fail every gated writer closed. Outside that
  one introduction patch, setup may seed Compatibility only on a proven clean
  install with no migration/index/accounting evidence; recovery after loss audits
  schema/history and reconstructs Recovery Required, never silently recreates
  Compatibility.
- Add restricted normal `NPO Membership Accounting Configuration`, one
  deterministic row per Company using NPO membership accounting, as the Request-
  mode opt-in, effective-
  configuration snapshot/version, capability-manifest hash, and issuance-versus-
  setting-change mutex. State is `Disabled`, `Fenced`, `Active`, or `Suspended`;
  service-owned transitions and missing/corrupt-row behavior follow activation-
  control anti-tamper rules. `Disabled` allows Invoice mode but rejects Request
  mode; `Active` allows both. Request opt-in is `Disabled -> Fenced -> Active`.
  The row stores a service-owned `fence_return_state`: maintenance uses
  `Disabled -> Fenced -> Disabled` for Invoice-only Companies or
  `Active -> Fenced -> Active` for Request-enabled Companies. Detected drift moves
  either operational state to Suspended; reactivation is `Suspended -> Fenced ->`
  the recorded, reverified operational state. No membership-accounting writer of
  either mode is allowed in Fenced or Suspended. Invoice-mode credit-limit
  enforcement/bypass policy is
  explicit; Request bypass is allowed only with fully locked funding.
- Add restricted normal `NPO Donation Accounting Configuration`, one deterministic
  row per Company, with `Disabled`/`Fenced`/`Active`/`Suspended`, return-state and
  anti-tamper behavior matching the membership control. It owns allowed/default
  timing, donation Item/effective UOM and precision, income/receivable, Gateway
  Clearing, Refundable Donation Receipts liability, tax/rounding/payment-term/
  credit-limit and acknowledgement-threshold policy, capability hash, and
  configuration version. Pledge credit-
  limit enforcement/bypass is explicit; On Receipt bypass requires captured funds.
  Holding and accepted event vouchers snapshot this exact row.
- Add `NPO Accounting Outbox` with unique event key, purpose/source, payload
  fingerprint (no credentials), status/attempt/error, lease token/expiry, and
  after-commit at-least-once delivery with receiver idempotency key;
  it is the only non_profit-owned path for external side effects from atomic NPO
  voucher creation. Retention may erase payload/error/lease detail after terminal
  delivery or administratively terminal dead-letter, but the row and unique event
  key remain permanently as the replay-prevention tombstone.
- Add `NPO Deferred Work` for transactionally durable internal dispatch. It has a
  globally unique work key, work type/source, required model version, payload
  fingerprint, status, lease token/expiry, attempt/error, and permanent terminal
  tombstone. Business transactions insert/reuse this row before commit; Redis
  enqueue is only a wake-up. A scheduler/operator sweeper enqueues Pending or
  expired-leased rows, and workers recheck the applicable activation/config row
  and source under lock before execution.
- Treat legal-form/UID fields from MiKi or another installed owner as optional
  evidence. This refactor does not transfer their schema ownership or create a
  competing field definition.
- Keep fields nullable during backfill.
- Keep every validator in compatibility mode. Merely migrating schema must not
  reject old records or change creation/accounting behavior.

### Phase 2.5: Resumable backfill and remediation

Run a dedicated, idempotent, resumable service per site. It is not a DocType
event hook and does not commit per record. Batches have deterministic boundaries,
savepoints, source fingerprints, and restart cursors; controlled standalone jobs
commit successful batches and leave blocking issues durable for review.

A dry run is read-only. Before an applied run, the current release commits
`Compatibility -> Backfill Fenced` for identity and every affected donation
control (plus Fenced for affected membership configuration), pauses external
writers, and drains relevant work. Normal identity/role/master/accounting writers
reject those states; only the migration operation ID may write. `NPO Identity Migration Run` has a database-
unique nullable active-run key plus lease owner/expiry. Every batch locks the
identity control and run rows, verifies Backfill Fenced, operation/model/source
fingerprint, cursor, and unexpired ownership, then renews the lease before writes.
A concurrent invocation or stale queued retry cannot process a batch or continue
after state/version changes. Successful completion clears the active key and may
return affected controls to their recorded Compatibility/Disabled state with the
approved fingerprint; failure remains Backfill Fenced/Fenced or Recovery Required
until explicit resume/abort verification.

Applied backfill has an activation-quality side-effect policy for Contact,
Address, Customer, Supplier, Member, Donor, Volunteer, Household, Party Link,
Dynamic Link, and migration/audit records. Under the committed fence it snapshots
and temporarily disables relevant Notification, Webhook, and Server Script
definitions; every installed app hook touching that set must declare and test a
backfill-safe capability that performs only transactional writes or the migration
outbox. Unknown/synchronous email, HTTP, Slack, realtime, or independently queued
effects block the run. Request-local callback/realtime buffers are cleared on
rollback, previous automation state is restored only after the completed
fingerprint is committed, and external summary/reconciliation work is emitted
once after the whole run. Good Connector duplicate-scan suppression is one member
of this general policy, not the sole containment mechanism.

Automatic backfill is limited to deterministic evidence:

- Adopt an exact single role-linked Contact only when subject type, Customer
  type, Contact identity kind, and all other role links agree.
- Infer Organization only from a Customer whose `customer_type` is Company or
  Partnership. Infer Person only from a proven Person Contact; core
  `customer_type = "Individual"` alone is insufficient because it also contains
  Household Customers. Infer Household only from explicit reviewed joint-party
  evidence. Leave every other Customer Unclassified and create a migration issue.
- Never choose the first email, first Dynamic Link, newest record, or fuzzy
  match. Those cases create migration issues.
- Backfill the explicit NPO-managed scope, accounting-master canonical Contacts,
  role direct Contacts, managed Dynamic Link projections, and alias status.
- Create NPO Organization links without collapsing operating Customers. Import a
  verified key only from approved verification evidence; format-valid MiKi UID
  text remains a claim/review item. Same-UID parent/child Customers share one NPO
  Organization only when legal-entity evidence proves that relationship, while
  `parent_organization` alone is insufficient.
- Backfill receipt jurisdiction only from explicit authoritative evidence. The old
  metadata/backend `Switzerland` default alone creates review, not a Swiss legal
  decision. Submitted receipts retain their exact historical country, language,
  renderer/template hash, and print compatibility; German-law `Donation Receipt
  DE` is never reclassified as Swiss output.
- Move future Swiss receipt/template/UID policy ownership to `good_npo` and Swiss
  QR/QRR transport ownership to Good Connector without rewriting stored historical
  QRRs or issued artifacts. Compatibility renderers remain until historical
  regeneration is proven.
- Relink legacy personal Addresses to Person Contact and organization Addresses
  to Customer/Supplier without deleting the source role link until equivalence
  is verified.
- Convert Household rows through the conditional conversion fallback when any
  data exists; preserve old rows until count/date/primary/Dynamic-Link checks
  pass.
- Backfill Household financial closure only from an explicit dated separation or
  approved accounting decision. A Household with financial history but no
  current people and no authoritative cutoff is a blocking issue; absence of a
  current row alone must not invent the closure date.
- Review inferred household Memberships as specified in section 7.4; do not
  invent contractual coverage.
- Do not infer Household Customer or Household Donor merely from residence,
  surname, address, or joint-looking bank text. Create a reviewed migration issue
  unless explicit payer/recognition evidence exists.
- Backfill every existing Donation to its explicit legacy Donor regime before
  any Customer-regime activation.
- Adopt every non-terminal or chargeback-capable legacy gateway checkout into a
  Donation Payment Intent using exact provider identity/status and preserved
  Integration Request evidence. Missing, ambiguous, or externally divergent
  provider state is blocking; no callback remains addressable only by a legacy
  Donation name.
- When Good Connector is installed, wrap every bulk
  Contact/Address/Customer/Supplier write batch in duplicate-scan suppression.
  Queue exactly one deduplicated full reconciliation only after the entire
  applied migration run reaches durable success, never once per batch or during
  a dry run. Without it, run the same required deterministic backfill and
  validations without optional duplicate-review jobs.

Manual remediation records the selected canonical identity, evidence, decision,
operator, timestamp, and affected records. Re-running reproduces the same result
or reports source drift; it never overwrites a reviewed decision silently.

The backfill is complete only when every source row is classified as converted,
approved alias, approved exception, or blocking issue, and all source/target
counts reconcile. Zero blocking issues is necessary but not sufficient for
enforcement; Phase 3 consumers and the verification matrix must also pass.

### Phase 3: Update identity and role creation

- Create/reuse Individual Member and Donor roles by canonical Contact.
- Create/reuse Organization Member and Donor roles by organization Customer.
- Create/reuse NPO Organization identity separately from operating Customer and
  Supplier projections; verified-key providers submit evidence through a
  versioned `non_profit` service rather than owning canonical identity.
- Introduce one financial-projection service that creates or reuses an
  Person Customer from canonical Contact at approved triggers.
- Introduce one Household financial-projection service that locks Household and
  creates/reuses its unique Customer at approved joint-payer triggers.
- Create Household Donor only through explicit joint-recognition or receipt
  selection and require it to use the same Household Customer.
- Seed/resolve exactly one controlled Anonymous System Customer and Donor through
  an idempotent restricted service; public flows select them only after explicit
  anonymous choice, never after failed or ambiguous person matching.
- Make Customer/Supplier pairing reuse the same canonical Contact for
  individuals and validated legal identity for organizations.
- Keep Supplier-only creation valid; do not create Customer without a
  receivable-side trigger.
- Maintain managed Contact Dynamic Link projections transactionally and resolve
  role form Contact/Address displays from canonical anchors.
- Make canonical anchors read-only/service-owned, allow retarget only after a
  zero-dependency preview, and route historical errors through split/
  consolidation rather than changing ownership.
- Add managed-DocType native rename/merge guards requiring the controlled
  operation ID, and NPO Party Link `on_trash`/unlink guards with approval/audit;
  ordinary unmarked Party Links remain untouched.
- Install the complete protected-lifecycle registry: cooperative v16 controller
  mixins, insert/discard/trash/restore hooks, serialization-sensitive generic-
  mutation guards, protected Version/Deleted Document audit handling, parent-only
  child mutation/read guards, DocShare mutex, privacy request overrides, protected
  RPC/export/print/File/timeline artifact perimeter, and activation-manifest
  entries must exist before any strict consumer is enabled.
- Run the metadata-preserving Contact Dynamic Link duplicate reconciler before
  core validation so NPO projection and MiKi relationship metadata cannot be
  discarded by core deduplication.
- Update Good NPO signup, public donation, imports, demo seeds, and all Desk/API
  helpers to use the same services.
- Implement the Good NPO Switzerland receipt/CH_UID providers and approved DE/FR/
  IT original/correction/reversal template manifest. Route every Household or
  individual recipient decision, issue, correction, numbering, render, and send
  through the snapshotted jurisdiction policy. Base-only and unsupported-
  jurisdiction receipts remain unissuable rather than falling back to German.
- Replace native Membership Website User email lookup/Contact-less creation with
  the locked User-to-canonical-Person continuation service; inventory/migrate Web
  Forms/external callers and fail activation on unresolved bindings or stale code.
- Gate public reuse/mutation on authenticated session or one-time canonical-
  endpoint proof; unresolved guests create opaque NPO Identity Claims and receive
  no candidate existence signal.
- Manage verified endpoints through the unique registry; Contact Email
  edit/remove/copy revokes value-bound claims under lock and concurrent Contacts
  cannot both verify one Personal endpoint.
- Keep the required services inside `non_profit`; optionally call Good Connector
  for candidate suggestions and duplicate review without changing the selected
  canonical record or validation outcome.
- Update Ilanga to create separate person identities and Contact-based Household
  rows; do not recreate the shared-couple Individual Customer.
- Migrate Volunteer away from `autoname = field:email`: assign stable generated
  names, preserve old names as aliases/external mappings, remove email as the
  mandatory unique identity, update incoming links through the controlled rename
  operation, and prove that later email changes do not rename or duplicate a
  Volunteer.
- Update the Household controller, Ilanga importer, Good NPO signup consumer,
  reports, docs, and tests behind the migration-version gate. Compatibility
  readers remain until every deployed site completes conversion; no code may
  write both models independently.
- Implement explicit Membership scope, covered-Member validation, Membership
  payer scope, Membership Type collection mode, and joint Household addressee
  rendering without treating Household residence alone as coverage or payer.
- Implement idempotent Membership Ask cycles and Invoice/Request settlement;
  validate Household/covered-Member payer choice and matching Customer projection
  before sending.
- Snapshot gross/net amount, explicit Item pricing, tax rows, and rounding policy;
  disable unintended pricing rules/discounts and reject any generated invoice
  whose final payable differs from fixed accepted amount.
- After all core mapping/defaults, pin controlled invoice/Credit Note posting
  date/time and due date; positive charge/recovery invoices get one non-discounted
  payment schedule, while returns finish with empty terms/schedule. Pin source
  return-row links and effective UOM/quantity precision, overwrite Payment Entry
  builder dates, and reject submit-time drift.
- Extend Sales Invoice composition to skip core common-party auto-accounting for
  all NPO purposes and apply the snapshotted purpose-specific credit-limit policy,
  calling `super()` unchanged for ordinary invoices.
- For Request mode, require Company-currency separate advance-liability
  configuration, dedicated ordinarily immutable ask-linked Payment Entries,
  audited terminal-attempt reassignment, standard
  explicit Sales Invoice Advance allocation, and the state/reversal model in
  section 7.4. Guard Payment Reconciliation and Unreconcile Payment as well as
  ordinary Payment Entry/Sales Invoice hooks so reserved advances cannot drift.
- Enforce one NPO owner per Payment Entry; allow only controlled same-Donation
  event references and disposition-bounded ordinary use of Free Residual/Released
  credit. Reject generic NPO voucher mutation before core locking and submit/
  cancel only from the owner-first focused Ask/Membership-cycle/Donation service.
- Reject every ordinary Journal Entry settlement/reference/reconciliation path for
  Membership Ask and Membership Subscription charge/reversal/recovery invoices
  and reserved advances; only the exact retained-credit NPO Credit Application
  matrix is allowed.
- Extend Payment Reconciliation candidate collection through a `super()`-calling
  v16 mixin that pre-limit filters/overfetches reserved, reassignment-pending, and
  refund-pending ask advances plus Donation excess-pending credit for both manual
  and Process Payment Reconciliation.
  Register the targeted `before_job` sanitizer for the hard-coded Process
  reconcile function; lock and mark stale persisted allocations skipped before
  core mutation rather than throwing and failing the full job.
  Add effective-config change guards for Company,
  Customer, Customer Group, Account, and reconciliation-date settings while open
  Request asks/payments depend on them; Ask issuance and every mutation lock the
  same per-Company NPO Membership Accounting Configuration rows.
- Implement cycle-root/attempt supersession, partial-ask refund/release, valid-
  advance reassignment audit, and Invoice/Request state derivation as one locked
  service rather than editable status fields.
- Route each partial/full Membership refund or release through one uniquely keyed
  NPO Refund Instruction/Source before creating its outgoing Payment Entry or
  Credit Note; retries and refund reversals reuse or supersede instructions, never
  duplicate vouchers.
- Implement reverse-payment refunds in ERPNext's tested direction (unreferenced
  outgoing Pay as invoice side, incoming Receive as payment side), with the narrow
  purpose/account-checked `set_liability_account` extension only for normal-
  receivable refunds and their recovered-cash Receive reversals when separate
  advances are enabled.
- Implement retained-credit release/application through uniquely keyed NPO Credit
  Application and exact purpose-marked two-row JE; exclude those Credit Notes from
  manual and Process debit/credit-note reconciliation.
- Freeze Request threshold-funded/acceptance dates from the crossing payment;
  use that open-period invoice date or require Posting Review with a reasoned
  first-open-date override instead of callback/job day.
- Reject Household scope for subscription-enabled Membership Types. Update the
  existing Individual/Organization Subscription helper to resolve and validate
  the Customer from the Membership subject rather than an unrelated fallback and
  assign the base Membership Subscription purpose/owner/cycle attempt to every
  generated invoice.
- Adopt existing Good NPO Membership invoices into those base owners under the
  fence; ambiguous/orphaned invoices block activation. Route first billing,
  renewal, Payrexx settlement, Credit Note/refund, cancellation, and retry through
  the focused owner service while maintaining the legacy mirror.
- For Subscription-backed charges, set/validate native `subscription`, `from_date`,
  and `to_date`; clear them on returns/recoveries. Extend managed Subscription
  process/generate/current-outstanding/cancel/restart/force/scheduler paths to use
  the same cycle mutex/disposition and allow later periods after a terminal fully
  credited/refunded cycle.
- Protect all managed Subscription billing scalars/Plan Detail rows and snapshot a
  versioned effective plan/price/tax/discount/due/dimension/period/cancellation/
  proration fingerprint under the Company configuration lock for each new cycle;
  generic changes cannot rewrite an open cycle.
- Link verified joint Bank Accounts to the Household Customer through standard
  `Bank Account.party_type = "Customer"`; preserve observed remitter evidence
  separately from recognition and receipt choices.
- Through the Good NPO Swiss payment-presentation adapter, extend Good Connector's
  Company-locked QRR registry/candidate scan with the one-owner Membership Ask
  rules: Invoice mode exposes Sales Invoice only; Request mode exposes Ask only and
  never its settlement invoice. No QRR rule is implemented in base `non_profit`.
- Preserve MiKi's organization-only `Membership -> Member -> Customer` contract
  and reject non-Organization Members, Person Customers, and Household Customers
  at both campaign and declaration boundaries. Preserve parent campaign targets,
  child Customer hierarchy, child-specific memberships, and declaration-item
  generation.
- Update every MiKi Sales Invoice mixin, defaulting, correspondence, dunning,
  escalation, export, permission, and status hook to recognize
  `npo_financial_purpose`. Donation, Membership Ask, and Membership Subscription
  invoices are excluded from generic MiKi ownership, as are their explicit
  Reversal purposes, and routed only through their owning non_profit flow;
  explicit MiKi declaration/case invoices remain unchanged.
- Update MiKi's site-wide Customer/Supplier Type Property Setters to restore
  ERPNext's `Company`, `Individual`, and `Partnership` options. MiKi imports may
  continue choosing Company and using their more precise legal-form field; the
  vertical app must not remove Partnership for every installed consumer.
- Install the Good Connector stable portal-subject adapter and the strictly app-
  scoped MoPi workforce and Barakah Supplier-set principal adapters; resolve them
  before custom dispatch, migrate explicit bindings, and reject every email/first-
  Customer or cross-app authority fallback.
- Update Good Analytics and MiKi newsletter providers plus Good Newsletter audience
  synchronization/delivery to carry canonical subject and verified endpoint
  version, invalidate future delivery on endpoint lifecycle change, and preserve
  consent/historical recipient evidence.
- Register every named consumer cleanup/retention operation from section 13.1,
  migrate stale jobs to versioned work keys, and replace email-fan-out/raw-delete
  behavior before lifecycle enforcement activates.
- Register and verify the Goodvantage receipt-source/NPO File and DocShare
  intersection policy in both app orders; list-query conditions, controller MRO,
  retargeting, and share validation must remain cooperative and fail closed.
- Log ambiguous matches for manual review instead of selecting the first record.
- Preserve existing helper signatures through compatibility adapters and emit
  the established telemetry for deprecated paths.

### Phase 4: Build consolidation and split controls

- Add read-only dependency previews for Contact, NPO Organization, Customer,
  Supplier, Member, and Donor/Volunteer consolidation or split.
- Implement the no-ledger merge versus archived-alias policy from section 9.
- Reconcile role dependencies explicitly rather than delegating the complete
  operation to `rename_doc(merge=True)`.
- Distinguish legal-organization consolidation from intentional operating
  Customer hierarchy. Transfer verified keys only after proving the legal entity;
  never merge MiKi operating units merely because they share a claimed UID.
- Record source IDs, decisions, counts, conflicts, operator, and effective date.
- Add explicit Household separation as a dated relationship operation.
- Include Household Customer, Donor, Bank Accounts, asks, advances, credits,
  Donations, receipts, and submitted accounting in separation previews; preserve
  the historical unit and block automatic repointing.
- Restrict preview to users who can read every surfaced record. Restrict
  execution to `System Manager` or `Non Profit Manager` with write access to all
  affected non-accounting domain records. An accounting-party operation requires
  `Administrator` or both `System Manager` and `Accounts Manager`, plus normal
  write access to every affected accounting master.
- Make previews redact records the operator cannot read and never expose PII
  through dependency counts or error text.

### Phase 5: Enforce identity invariants

This phase is a separate per-site activation command. It refuses to start unless
the persisted migration run matches the installed model version, has zero
blocking issues, reconciles all counts/fingerprints, and the required cross-app
verification suite passed for the release. Operations first take a shim-managed,
externally manifested pre-maintenance backup, deploy the fence-aware release to every web/worker/
scheduler process, and pause external writers; maintenance mode is an operational safeguard, not a
substitute for the database fence. It uses the fixed normal-DocType
`identity` activation row and an explicit state machine:

Applied backfill:

`Compatibility -> Backfill Fenced -> Compatibility`

Initial activation:

`Compatibility -> Fenced -> Installing Indexes -> Verifying -> Active`

Post-activation maintenance:

`Active -> Fenced -> Installing Indexes -> Verifying -> Active`

`Recovery Required` records an interrupted or conflicting activation;
`Suspended` fails closed after activation. Every identity-key writer acquires an
uncached database permit on the control row and rejects ordinary writes while
backfill-fenced, fenced,
installing, verifying, recovering, or suspended. The activator acquires a
database named lock plus the row `FOR UPDATE`, commits the fence so earlier
writers drain. After every writer/callback/job is dispositioned and before the
first DDL or model-changing write, operations take and verify a second
authoritative shim-managed post-fence database/files/config backup plus binlog/
external generation-manifest fingerprint. This is the rollback baseline because no valid writer can commit
after it. The activator then reruns all counts, fingerprints, and duplicate
checks.

Identity is activated before any financial control and remains their parent gate.
Donation accounting and each Company donation/membership configuration can return
to an operational state only when identity is Active with the same approved
migration run, epoch, and capability hash. Leaving identity Active is one parent-
first locked operation that fences every dependent financial control/configuration
before committing the identity state; independent per-control transitions are not
allowed to violate that dependency.

Activation requires the declared deployment-owned `party_model_epoch_provider`.
Its authenticated interface is `read(site_id)` and compare-and-swap
`advance(site_id, expected_epoch, target_epoch, capability_hash)` with durable
external audit, signing-key rotation, and process-cache invalidation semantics.
The provider derives deployment/site UUID/incarnation from the same site-scoped
workload credential; `site_id` is an assertion, cross-site credentials/context and
clone/rename namespace reset fail without existence disclosure. Controlled rename
retains UUID/incarnation; protected-history clone is rejected, while same-
incarnation disaster recovery uses the backup/restore shim.
Under the fence, the activator computes one target, performs CAS, requires the
signed epoch/hash to be durably visible to every web/worker/scheduler/callback
process, and only then commits Active. A crash before CAS leaves the DB target
uncommitted; a crash after CAS but before DB activation enters Recovery Required
and fixes forward to that target rather than decrementing the anchor. Absence,
provider outage, stale cache, invalid signature, lower/different DB epoch/hash, or
site-ID mismatch blocks activation and all protected process entry before Deferred
Work/Outbox/provider replay. Only trusted-host recovery may reconcile/advance the
external anchor, which is never included in ordinary site backup artifacts.

Every boot/request/read/write/worker/scheduler/callback/provider/outbox path also
validates the external runtime generation lease. Protected transactions retain the
lease and recheck the uncached fencing token before final write; external delivery
does so immediately before send. Forced DR promotion waits for surrender or lease
expiry/revocation, CAS-advances generation, and revokes old workload credentials
and ingress/static routes before the restored generation can start. Runtime-
generation mismatch fails closed independently of a matching model epoch.

Worker drain includes a persisted queue-disposition manifest, not merely stopping
processes. Inventory RQ queued/deferred/scheduled/failed registries, scheduler
events, Deferred Work, Accounting Outbox, provider callbacks, email queues, and
all installed app jobs whose payload can touch a protected DocType. Each item is
fingerprinted and marked `Drained under old model`, `Cancelled with audit`,
`Migrated`, or `Versioned replay after Active`; an unknown or stale payload blocks
activation/upgrade. Every new NPO job carries model version and idempotency/work
key and checks the applicable uncached control before execution. Restart cannot
run an old payload under new semantics, and stale failed jobs cannot be retried
outside their recorded disposition.

The approved installed-capability manifest is part of that fingerprint. It
contains installed app names/order/versions, declared NPO party-model capability
versions, required fields, provider/materializer paths, receipt-jurisdiction
provider/policy/template-manifest versions, effective hooks, and the
relevant Sales Invoice/Payment Reconciliation/Payment Entry class MRO plus the
enabled voucher-automation/outbox policy hash. Activation
verifies the exact site's installed set, not only a CI suite from another stack.
Receipt provider/template drift fences legal receipt issue/correction/send only;
it does not disable unrelated identity/accounting writers when generic receipt
facts and claims remain compatible.
Relevant app install/uninstall/upgrade/hook-order change recomputes the manifest
in setup hooks. Unexpected drift while a control is operational persists
Suspended directly. Expected drift while every affected control is already
Fenced remains Fenced only when its operation ID and precommitted target
app/schema/capability-manifest hashes match the running upgrade; a mismatch enters
Recovery Required, never Suspended or Active. Every gated writer also compares
the computed hash and fails closed on mismatch even while a stored operational row
has not yet been suspended; safety never depends on committing Suspended in the
failing writer's transaction. An `after_rollback` callback queues a deduplicated
  fresh transaction that locks and persists the affected operational identity/
  donation and Company donation/membership controls as Suspended. The new combination must pass migration/
preflight and explicit reactivation.

Every post-activation install, uninstall, upgrade, branch/image replacement, or
hook-order change that can affect the model uses a pre-operation fence command
from the currently running release. The command records the approved target app/
version/manifest artifact before any package/schema mutation; direct `bench
install-app`, `uninstall-app`, or migrate without that matching fence aborts in
setup/before-uninstall. `Active -> Fenced` is an explicit valid maintenance
transition for identity and donation accounting; active Membership Accounting
and Donation Accounting Configuration rows use `Active -> Fenced -> Active`, while
disabled rows use `Disabled -> Fenced -> Disabled`; the committed
`fence_return_state` prevents the new release from guessing. The command locks and commits the relevant controls as
Fenced,
drains/stops web workers, schedulers, and external callbacks, then permits code/
image replacement and `bench migrate`. Migration aborts if a relevant active
model was not fenced before code change. After all processes run the new release,
the site recomputes schema/capability/automation manifests, reruns focused
preflight, and explicitly returns Active. Runtime hash checks are defense in depth,
not a substitute for fencing stale old workers before DDL or hook changes.

The fence is attached to Frappe's actual pre-mutation entry points. `non_profit`
registers central `before_app_install`, `before_app_uninstall`, and `before_migrate`
guards plus its own `before_install`/`before_uninstall`; guarded bench command
wrappers verify the committed permit before invoking install/migrate/uninstall.
Production's installer/container entrypoint shim performs that check before core
imports or invokes an unknown target app, so arbitrary target `before_install` code
cannot run first through a sanctioned command.
Because the target app's own `before_install`/`before_uninstall` runs before the
global app hook, every relevant Goodvantage consumer registers the shared guard as
its first target hook as well. Hooks only verify/throw and never create or commit a
fence. Direct Python/bench-code execution by a host operator can run arbitrary app
code and is explicitly part of the trusted-host boundary, not something an app
hook can sandbox. The effective command/shim and hook paths/order are part of the
capability manifest.

The live `update_installed_apps_order` RPC and every equivalent installed-order
writer are explicitly overridden. On a protected-history site only Administrator
may invoke them, and only with a committed target-manifest operation after all
affected identity/donation/membership controls are Fenced and processes/callbacks
are drained. The controls remain Fenced until installed order, effective hooks/MRO,
and capability hash are reloaded and verified by every process; stale/mismatched
permits or mixed-order workers fail closed. Direct config mutation remains a
trusted-host operation subject to the same operational fence.

Even a permitted clean `non_profit` uninstall requires its own committed lifecycle
fence row, site maintenance, external/worker drain, final no-history/schema/source
recheck under the database named lock, and matching operation ID in
`before_uninstall`. The row remains if uninstall fails; if removal succeeds, its
exported non-PII audit is stored in the site-private operation log before the app
tables disappear. A point-in-time clean check without that fence is insufficient.

MariaDB index DDL implicitly commits, so activation is intentionally resumable,
not falsely transactional. An explicit manifest records each expected unique
index or activation-owned effective-metadata override. The activator inspects the
actual schema, installs one hardcoded entry at a time, checkpoints after each
DDL, re-verifies the complete manifest and data under the write fence, and only
then commits Active. Before the first successful DDL, an initial activation whose
recorded origin was Compatibility may return to Compatibility after inspection.
A maintenance fence whose origin was Active never returns to Compatibility: it
may return to Active only after the exact old release/image, schema, and
capability manifest have been restored and reverified; otherwise it remains
Fenced or enters Recovery Required. After any successful DDL, failures remain
fenced as Recovery Required and must resume/fix forward. Active never flips back
to Compatibility.
Nullable active keys use SQL `NULL` for aliases, and later `bench migrate` runs
must preserve the activation-owned uniqueness metadata/indexes. A true rollback
after the DDL boundary and before Active uses only the verified authoritative
post-fence generation through the quarantine/reconcile/promotion shim, never the
earlier pre-maintenance backup or direct live extraction. After Active has
accepted Customer-model vouchers, callbacks, or outbox delivery, pre-cutover
restore is forbidden: operations fence/quarantine writers and providers, preserve
the incident snapshot and external idempotency evidence, then fix forward or use
a reconciled point-in-time restore/log replay that accounts for every post-backup
voucher, File, callback, Refund/Economic Receipt source, Deferred Work, and outbox
event. Ambiguous email/Slack delivery remains quarantined for manual disposition
rather than being replayed as unsent.

- Enforce one active canonical Person Customer per canonical Contact;
  archived accounting aliases are excluded and blocked from new activity.
- Enforce one active Household Customer per Household and mutually exclusive
  Person/Organization/Household/Anonymous System Customer identity anchors.
- Require `npo_subject_type` on every active NPO-managed Customer. Person,
  Household, and Anonymous System use ERPNext `customer_type = "Individual"` as
  separate NPO subjects; only `npo_subject_type` determines their identity rules.
- Require the read-only NPO-managed marker on every Customer/Supplier used by an
  NPO role, projection, adopted NPO Party Link, Membership Ask, or Donation
  accounting; unrelated ERPNext masters and links remain outside the model.
- Enforce the subject/core-type/required-anchor matrix in section 5.2: Person
  requires only its Person Contact anchor, Household requires only its Household
  anchor, Organization requires Company or Partnership core type plus NPO
  Organization, and Anonymous System requires only its unique system key.
- Require canonical Contact on every active Customer with
  `npo_subject_type = "Person"` and on every active NPO-managed Individual
  Supplier.
- Enforce exactly one active Anonymous System Customer and Donor with the
  `ANONYMOUS` key and no person, organization, Household, communication, or
  receipt-recipient anchor.
- Exclude Anonymous System parties from normal selectors and enforce the explicit
  Donation-purpose transaction allowlist across orders, invoices, memberships,
  subscriptions, payments, shares, imports, and direct APIs.
- Enforce one active NPO-managed Individual Supplier per canonical Contact.
- Require every NPO-managed Organization Supplier to use Company or Partnership
  core type and link an NPO Organization.
- Enforce one active Individual Member and one active Individual Donor per
  canonical Contact.
- Enforce one active Organization Member and one active Organization Donor per
  organization Customer.
- Enforce one active Household Donor per Household when joint recognition is
  used; its Customer must be that Household's Customer projection.
- Require subject type on every active Member and Donor.
- Require Contact on Individual Member and Donor, except the explicitly marked
  anonymous system Donor.
- Require Customer for Organization roles but keep it optional for Individual
  roles until a financial trigger.
- Require an Individual role's Customer, when present, to be an Individual
  Customer anchored to the same canonical Contact.
- Require an Organization role's Customer to have `customer_type` Company or
  Partnership and link an NPO Organization.
- Enforce one Volunteer per canonical Contact.
- Enforce one current financial Household per Contact and one current primary
  person per Household. Moving/separation closes the prior dated row before the
  next current relationship can begin.
- Require Person identity kind for Individual roles, accounting projections,
  Volunteers, and Household people; Generic Endpoint and Unclassified cannot
  satisfy those links.
- Require managed Dynamic Link projections to agree with direct canonical
  fields, and require Address relocation verification before retiring role-only
  links.
- Enforce dependency-based canonical-anchor immutability and block native
  rename/merge/unlink bypasses unless the active audited operation owns them.
- Enforce explicit Membership scope and covered-Member overlap rules.
- Enforce Household Membership payer scope, optional billing Member, matching
  Household/Person billing Customer, unique Membership Ask cycle keys, and
  immutable linked accounting documents.
- Require Household Bank Accounts used for automatic payer matching to reference
  the Household Customer; bank ownership evidence never changes Donor or receipt
  recognition automatically.
- Enforce unique canonical keys on NPO Organization Verified Key, while allowing
  reviewed operating Customers to share one organization and leaving
  unidentified organizations review-based.
- Require Active Projection Approval for new-use NPO Organization Customer/
  Supplier links and Settlement Only approval for retained historical links;
  Revoked requires zero-dependency unlink. Enforce verified-key lifecycle/
  tombstone/transfer action history; a shared key or parent hierarchy cannot
  substitute for approval.
- Enforce alias lifecycle fields, canonical target type, new-activity blocks,
  Settlement Only exact-party operations, and final disabled state where
  available.
- Enable strict one-to-one Party Link validation only for links with reviewed
  NPO-managed endpoints, after those links and canonical Contacts have been
  audited/backfilled; preserve ordinary unmarked ERPNext Party Links.
- Remove `Customer.household`, role-owned household state, and inferred
  `Membership.is_household_membership` only after Household and Membership
  migration is complete on every supported site. Explicit Household scope does
  not require joint invoicing; billing remains separately gated.

### Phase 6: Align Donation accounting

Execute only after the accepted Customer-accounting direction is activated in
requirements and the complete per-site accounting preflight passes.

- Complete and persist the all-Donation legacy-regime backfill from section 8.2.
- Activate each Company Donation Accounting Configuration only under the same
  Active identity/donation epoch after timing-policy, account/Item/UOM/Tax/terms/
  precision and open-work compatibility preflight; guest/API input cannot choose
  pledge timing.
- Add the immutable accounting model/timing/party fields and Donation-linked
  Sales Invoice event key. Configure and validate the donation Item, income,
  receivable, clearing, dimensions, and tax policy.
- Build donation invoices from explicit pricing/tax/rounding snapshots with
  unintended pricing rules/discounts disabled, and require final gross payable
  to equal Accounting Event accepted amount before voucher submission.
- Pin explicit posting date/time, legal due date, one non-discounted payment
  schedule, source return-item links, and effective quantity precision after core
  defaults/mapping; overwrite Payment Entry builder dates and recheck before
  submit.
- Apply Donation credit-limit policy and verify NPO purposes cannot trigger
  ERPNext common-party auto-reconciliation Journal Entries.
- Implement `Receivable on Submit` and atomic `On Receipt` Sales Invoice/Payment
  Entry services. Customer-regime Payment Entries reference Sales Invoice only;
  do not add a Donation reference mixin to the Payment Entry class.
- Implement service-owned Holding Capture/Reclassification/Refund Journal Entries
  for captured review/refund-required funds, with exact Economic Receipt,
  clearing/liability, date, and invoice invariants.
- Require one uniquely keyed NPO Refund Instruction/Source for every accepted-
  gift, pledge, excess, holding, provider, and chargeback refund tranche before
  creating a Credit Note, outgoing Payment Entry, or Holding Refund Journal Entry.
- Implement disposition-specific refund recovery: collectible no-cash forward
  charge, cash-gated On Receipt/refund recovery, advance/excess reverse-payment,
  Holding recapture, and consumed/unconsumed Retained Credit handling.
- Guard every Posted On Receipt invoice/payment pair from ordinary
  cancel/reconcile/unreconcile/reallocation regardless of receipt status; expose
  only the audited event Void/Reattribute/refund operations.
- Reject ordinary/untyped Journal Entry settlement/reference paths for
  Customer-model Donation invoices in V1, including reconciliation and
  update-after-submit bypasses; permit only exact purpose-marked Holding
  Reclassification and Released-Credit Application matrices.
- Enforce Company-currency V1 plus immutable source/payment/posting dates; closed
  periods require explicit reviewed posting-date override without changing the
  legal receipt date.
- Add the optional Good Connector post-lock transactional materializer while
  preserving its side-effect-free candidate provider, aggregate ambiguity check,
  Payment Entry submission, and Bank Transaction-link ownership. Candidate,
  materializer, failure-status, and retry paths hold/recheck identity, donation,
  and Company configuration permits through their respective commits.
- Implement generic Donation external-reference lifecycle hooks in `non_profit`.
  The Good NPO/Good Connector Swiss adapter implements one-owner QRR routing:
  pledge Sales Invoice only, On Receipt Donation only, no QRR owner/candidate on
  Payment Intent or settled event invoices, and locked legacy-to-continuation
  handoff in Good Connector's Company registry.
- Update new voucher construction and reconciliation to dispatch from the stored
  model while keeping legacy direct-Donation invariants in doc-events.
- Disable new direct legacy Donation allocations after cutover; preserve only
  exact historical interpretation/correction and use Customer-model continuation
  Donations for future funds.
- Freeze the Donation accounting party on insert/submit as defined in section
  8.2.
- Keep historical Donor party references readable and prevent mixed allocation.
- Redesign Donation Receipt items around immutable eligible payment allocations
  and deterministic claim rows so partial/cross-period/concurrent receipts cannot
  duplicate amounts. Preserve legacy print/items, reviewed manual evidence, and
  generic provider-selected correction/reversal lineage for post-receipt refunds.
- Verify Donation outstanding amounts, receipt qualification facts/claims, bank
  reconciliation, donor analytics, and statements.
- Activate the explicit per-site cutover version under the locked
  `donation-accounting` activation row; do not infer model from date at runtime.
- Verify Payrexx, manual Payment Entry, QRR/EBICS, cancellation, amendment,
  recurring generation, pledge/On Receipt timing, refunds/chargebacks,
  reconciliation/unreconciliation, receipt, and analytics behavior in both
  models before activation.

### Phase 7: Remove legacy paths

- Register `before_uninstall` to veto removal of `non_profit` once any activation
  left clean Compatibility or any protected identity, migration, NPO-purpose
  voucher, Economic Receipt/Event/Intent, claim, receipt, lineage, alias, or audit
  history exists. Uninstall would delete the fence and custom DocTypes/fields, so
  manifest suspension is insufficient. Removal then requires a separately
  reviewed offline destructive migration/restore; a genuinely clean unactivated
  site may uninstall only through the committed lifecycle-fence/drain/final-
  recheck protocol in Phase 5.
- Keep current helper/API dotted paths as adapters over the new services. Mark a
  path for removal only after at least 90 days of telemetry and one complete
  release cycle with zero calls, matching the existing compatibility contract.
- Inventory external API payloads and use additive/versioned changes; persisted
  or external consumers do not lose fields merely because internal lookup moved
  to canonical Contact.
- Remove Member Party Type registration.
- Stop new Donor Party Type registration only when no new Donation uses it.
- Remove obsolete Household fields and old child data only after all supported
  sites have a verified conversion or an explicitly recorded empty preflight.
- Retain compatibility only where persisted accounting or external API contracts
  require it.
- Keep legacy Donor Party Type and Donation regime readers as long as any
  supported site has historical rows using them; zero new use is not enough to
  delete historical interpretation.

## 11. Proposal Decisions And Remaining Gates

Resolved discussion choices are still non-authoritative until activated through
the traceability boundary above. Open items remain implementation gates.

| # | Decision or question | Status | Direction |
|---|---|---|---|
| 1 | Accounting party for new Donations | Resolved | Customer through Donation-linked Sales Invoice; Donor remains fundraising attribution and new Customer Payment Entries never reference Donation directly. |
| 2 | Existing production Donor accounting history | Reported none; mandatory preflight remains | Audit every deployed site and accounting table. Use a clean cutover only when the persisted audit proves zero history. |
| 3 | Anonymous Donations | Resolved | One controlled Anonymous System Donor and Customer with unique `ANONYMOUS` keys and no Contact/Household/organization/receipt recipient. Never use ambiguity as anonymous choice or merge identified people into it. |
| 4 | Customer creation for paid Membership | Resolved direction | Create the matching Person or Organization Customer before an Individual/Organization Subscription or Sales Invoice. Create the matching Person or Household Customer before a family joint ask according to Household payer scope; Household Memberships initially do not use ERPNext Subscription. |
| 5 | Family Membership joint ask | Resolved | One Household-scoped Membership, explicit covered Members, payer scope Household or Covered Member, one matching billing Customer, and one joint ask addressed to Household. Membership Type collection mode decides Invoice versus non-ledger Request. |
| 6 | Household as Donation/tax-receipt addressee | Resolved | Base supports an explicit Household recipient candidate and immutable joint snapshot; legal entitlement belongs to the selected jurisdiction provider. The Switzerland V1 policy in `good_npo` approves Household Donor plus Household Customer for jointly given funds, while personal giving keeps individual receipts. |
| 7 | More than one current Household per Contact | Resolved | No. Enforce at most one current financial Household per Contact and preserve prior Households as dated history. Moving or separation closes the old row before a new current relationship begins. |
| 8 | Corporate volunteering | Resolved | Keep Volunteers person-based; link them to organizations through a future Volunteer Engagement model rather than making organizations Volunteers. |
| 9 | Physical merge with submitted ledger history | Resolved | Do not physically merge accounting parties with submitted history. Archive as aliases and route only supported future activity to the canonical party. |
| 10 | NPO-facing Customer label | Resolved | Display Constituent Account in NPO presentation while preserving ERPNext `Customer` internally and in accounting contexts. |
| 11 | Good Connector dependency | Resolved | Remains optional. `non_profit` owns every required invariant and ERPNext-only fallback. |
| 12 | Existing Household Membership contractual coverage | Deployment gate | Treat every inferred flag as review-required unless an approved source mapping proves covered people. |
| 13 | Organization identifier schemes | Resolved for V1 | `non_profit` owns a scheme-neutral verified-key registry and ships no country normalizer. V1 enables only `CH_UID` through `good_npo`; later schemes require their own provider, normalization, authority, and uniqueness rules. |
| 14 | Generic communication endpoints | Resolved | Keep separate Generic Endpoint Contacts; never overload the Person identity Contact. |
| 15 | Household financial projection | Resolved | Household may have one optional Customer projection and one optional Household Donor; standard ERPNext accounting uses the Customer, not Household as a custom Party Type. |
| 16 | Household recurring billing | Resolved initial direction | Use idempotent Membership Ask cycles; reject subscription-enabled Membership Types for Household scope until a separate Subscription synchronization design is approved. |
| 17 | Verified organization identity versus operating Customer | Resolved architecture direction | Store legal identity and verified keys in base-owned NPO Organization records. Customer/Supplier remain ERPNext projections; reviewed MiKi parent/child operating Customers may share one legal identity without merging. |
| 18 | Donation income timing | Resolved | Default ordinary voluntary gifts to `On Receipt`; permit `Receivable on Submit` pledges only under the approved per-Company Donation Accounting Configuration policy, service-derived and never guest-selectable. V1 is Company-currency and preserves source payment date separately from reviewed posting date. |
| 19 | Request-mode advance reservation | Resolved initial direction | Use dedicated ask-linked Customer Payment Entries, Company-currency separate advance liability accounting, one standard Sales Invoice with explicit advances, and guarded reversal/reconciliation paths. Company-wide opt-in requires compatibility preflight and open-ask configuration guards. |
| 20 | Nonresident family dependants | Deferred | Initial covered-Member intervals must fit Household Person intervals. Add nonresident dependants only with an explicit eligibility policy. |
| 21 | NPO-generated Sales Invoice ownership | Resolved architecture direction | Base `npo_financial_purpose` marks Donation, Membership Ask, and Individual/Organization Membership Subscription invoices plus their reversals/recoveries; MiKi and other vertical hooks must exclude or explicitly route them rather than claiming unmarked generic invoices. |
| 22 | Abandoned partial family ask | Resolved initial direction | Preserve real incoming Payment Entries; controlled operation refunds them or releases ordinary Customer credit, then permits one audited successor attempt. |
| 23 | Legacy Donation writes after cutover | Resolved | Preserve historical interpretation/corrections only. Convert or close unledgered rows under the fence and reject every new direct Donor allocation after activation. |
| 24 | Donation Receipt refund correction format | Resolved for Switzerland V1 | `non_profit` owns generic correction lineage only. `good_npo` issues one separate immutable negative correction per finalized post-receipt refund, referencing the original and using a dedicated correction series; refund undo creates a reversing correction. It renders approved DE/FR/IT templates, sends automatically to the frozen donor recipient, and creates no authority-notification workflow. |
| 25 | Donation checkout cancellation | Resolved architecture direction | Persist provider-neutral Payment Intents; block cancellation while any intent/receipt observation is live and route late capture to controlled reattribution/refund without income on a cancelled Donation. |
| 26 | Partly funded legacy Donation | Resolved | Future funds use one Customer-model continuation under immutable lineage and reviewed remaining intent; root reporting and generic external-reference handoff prevent double collection/counting. The Swiss adapter additionally transfers or retires QRR under lock. |
| 27 | Swiss Membership Ask QRR owner | Resolved integration policy | When the Switzerland presentation enables QRR, Invoice mode exposes Sales Invoice only and Request mode exposes Membership Ask only; its settlement invoice has no QRR. `good_npo` owns the Swiss use/presentation policy and Good Connector owns QR-IBAN/QRR generation, validation, collision registry, and bank transport. |
| 28 | Receipt jurisdiction selection | Resolved | Jurisdiction is selectable on each draft/generation request and frozen with provider/policy/template versions at issue. `non_profit` remains generic; V1 implements only Switzerland through `good_npo`. Unsupported jurisdictions remain storable but fail closed for issue/correction until a provider is installed. |

## 12. Permission And PII Contract

Strict identity must not grant broad access to ERPNext masters. Canonical fields
use a restricted permission level where needed, and public/system services return
only domain record identifiers already authorized for the caller.

Frappe's generic mutation responses are not a field-permission boundary:
`frappe.client.set_value/save/insert/submit/cancel`, REST v1 update/create, and
REST v2 document methods can serialize the full in-memory document without first
applying field-level read permissions. The protected-lifecycle registry therefore
also marks **serialization-sensitive** records. Generic create, write, submit,
cancel, and whitelisted document-method permission succeeds for such a record
only when the caller has the raw-read authority required for every canonical
field and child row that the response may contain. For standard DocTypes this is
conditional on the persisted or requested row being NPO-managed/NPO-purpose;
unmarked ERPNext records keep ordinary behavior. A caller with narrower business
authority uses a purpose-specific service that accepts an allowlisted command,
checks/locks the parent and targets, and returns a newly constructed redacted
result rather than a Document or `as_dict()` payload. Public identity/accounting
creation uses only those services. Create guards examine requested anchors and
purpose before insert, so omitting a marker cannot cause server classification
and a leaked full response.

Every protected document/business mutator is declared POST-only and independently
checks operation authority, controls, locks, and idempotency inside the method.
Cooperative dispatch guards make REST v1 `run_method`, REST v2 document methods/
`run_doc_method`, and normal RPC all enforce the method's declared HTTP verbs
before invocation; GET, HEAD, and OPTIONS are side-effect-free even when the caller
has document read permission. A rejected read-verb call may not create DB/file/
Redis locks, queue/email work, external effects, or disclosures, and no explicit
commit is accepted as a substitute for this boundary. Dispatcher paths/hashes are
activation capabilities.

Core Version timelines are not safe for protected PII either: `Version.data`
contains full field/child diffs and Desk loads it with `get_all`. For a
serialization-sensitive row, the security lifecycle mixin overrides
`save_version` and does not call core Version creation. It writes an immutable,
restricted `NPO Protected Change Audit` in the same transaction with protection
domain, actor, operation ID, changed-field names, and raw before/after evidence
available only under the corresponding raw identity/accounting authority; the
ordinary timeline receives at most a separately constructed non-PII summary.
Unmarked standard ERPNext rows continue through cooperative `super()`. Before
activation, every existing Version for a protected row is copied/fingerprinted
into the restricted audit and its public `Version.data` is removed or replaced
with a validated non-PII summary. Direct Version permissions are also restricted;
activation blocks until no raw protected diff remains reachable through form
docinfo, list, report, export, REST, or RPC.

Print/email presentation is equally explicit because Print Format Jinja receives
the full document. One `assert_protected_render_authority` policy is invoked by
the protected controller `before_print` for classic rendering, explicit overrides
of direct WeasyPrint download/HTML endpoints, and guarded Communication/email/
Notification attachment builders before any direct `PrintFormatGenerator` or
`attach_print` call (the latter sets `ignore_print_permissions` itself).
Protected `has_permission("print")` also fails closed for generic generators unless
matching raw authority is present. The capability manifest inventories and hashes
every installed direct print/PDF generator callsite; an unguarded callsite blocks
activation.
`get_document_share_key` on a protected document and `Document Share Key.insert`
for a persisted/requested protected target both fail closed; activation revokes
and audits every existing key for a protected target. Generic email cannot attach
or link a protected print for a partial reader. Recipient-facing membership,
donation, and receipt correspondence renders only from its immutable approved
snapshot through a purpose-specific service and returns/sends that artifact, not
a generic document URL. The effective print guard and Document Share Key class
MRO are activation capabilities.

Administrative read tools do not bypass the same rule. A cooperative Audit Trail
extension requires matching raw authority on the selected document and every
amended document immediately before loading/diffing them; partial readers use NPO
Protected Change Audit's redacted projection instead. Overrides for
`frappe.desk.form.linked_with.get` and `get_submitted_linked_docs` permission-check
every discovered target. For protected roots or targets they never use
permission-bypassing totals, never return hidden IDs/counts, and either return
only authorized rows or fail the cancel-all request generically if an inaccessible
dependency makes a complete result unsafe. Unprotected roots retain standard
behavior except that protected targets remain omitted without `hidden_count`.
These overrides and Audit Trail MRO are included in the capability manifest.

A versioned protected-RPC/export registry covers upstream module functions that
can bypass document permissions or reveal discovery metadata. At minimum it
overrides ERPNext party-detail/primary Contact/Address/bank-account helpers,
rejects caller-controlled `ignore_permissions` for NPO-managed parties, and
permission-checks every returned Contact, Address, Bank Account, and Dynamic Link.
It also overrides Desk `get_open_count` and `get_link_title`, Link/Awesomebar
title resolution, and any installed equivalent: protected targets yield neither
internal IDs, titles, counts, nor existence signals without target authority.
Data Export/report download for a protected parent requires raw authority for all
selected parents and children and builds rows from the permission-filtered
projection; core parent export may not fetch child tables directly. Partial users
receive only named redacted exports. The registry records exact dotted paths,
signatures, source/version hashes, and effective `override_whitelisted_methods`;
upstream drift or an unclassified public ignore-permission parameter blocks
activation.

Dashboard Chart is a protected aggregate RPC, including caller-supplied chart
definitions, creation, Heatmap, cache load, and equivalent dashboard endpoints.
For a protected source, callers cannot supply/construct a chart without source
authority, providers use permission-aware queries rather than `get_all`, and every
returned aggregate is authorized before computation. Cache keys include chart
definition/name, complete filters/date range, requesting user, source/formula
version, and current row-authorization fingerprint; shared caching is disabled
where that fingerprint cannot be proven. Permission/configuration change revokes
stale cache entries, and unauthorized access reveals no count/date/sum signal.

Prepared Report, Auto Email Report, report File, and equivalent multi-source
containers inherit the strongest source-row domain. Generation stores report/
filters/formula version, requesting user, row-authorization fingerprint, source
IDs hash, and private File. Download requires the same owner (or matching raw
authority), current report permission, and a recomputed authorization fingerprint;
report-name permission alone is insufficient. Scheduled email regenerates under
each currently authorized recipient and sends only if every row remains allowed;
stale/broader artifacts are revoked. Query/Script report providers must apply NPO
row authorization before aggregation. Existing prepared/emailed reports and Files
are inventoried, reclassified, or deleted before activation.

The application trust boundary is explicit. Host/OS/database operators and the
Frappe `Administrator` account are trusted recovery authorities; ordinary `System
Manager` is not. User/Has Role mutation, Role/DocPerm/Custom DocPerm, Role Profile,
Server Script, Report, Print Format, Webhook/Notification, and security-setting
guards prevent a System Manager from self-assigning Accounts Manager/protected
roles, changing the accounting conjunction, or enabling a bypass. Such changes
require Administrator plus fence/audit where they affect capabilities. System
Console/safe-exec and full backup/download endpoints are denied to non-
Administrator while protected history exists; direct bench/SQL access is a
trusted-host action outside the app threat boundary and is recorded operationally.

Authority takeover is evaluated from both persisted and requested User state, not
only self-assignment. Only Administrator may grant a protected role or change the
password, API credentials/keys, sessions, 2FA/reset state, enabled flag, user type,
email/login identity, or Role Profile of an account that holds or is being granted
protected authority. The guard serializes User plus Has Role rows and blocks both
credential-then-role and role-then-credential sequences through Desk, import,
REST/RPC, password reset, and `generate_keys`. Generic password-value retrieval
(`get_password` and equivalents) requires permission on the exact target/field and
matching protection-domain authority; a System Manager cannot retrieve or reset a
second authority's credential to collapse the conjunction.

Frappe User impersonation is not a role-based escape. The exact
`frappe.core.doctype.user.user.impersonate` endpoint and equivalents require the
literal Administrator account while protected history exists; role/Custom DocPerm
`impersonate` grants are rejected and removed under activation audit. Existing
sessions with `impersonated_by` are invalidated. Every protected authority check
also reads session provenance and rejects any impersonated session, including one
started by Administrator, until it switches back; neither target roles nor a
forged/old session can satisfy the identity/accounting conjunction. The endpoint,
session invalidator, and authority predicate are manifest capabilities.

Strict activation disables database-authored Server Scripts of every type and
custom Query/Script Reports unless they have been migrated to reviewed app source
with a manifest hash and permission-aware provider. Safe globals such as
`get_all`, `db.set_value`, delete, sendmail, print, API/Scheduler/Permission Query
scripts, and dynamic SQL are never accepted as protected runtime policy. Installed
source reports/templates/scripts are inventoried for protected reads/writes and
must declare row authorization and output protection; unknown source/hash drift
blocks activation. This programmable-artifact policy is enforced at enable/save/
execute time, not only by lint.

Files and timeline artifacts inherit protection rather than relying on their
owner alone. A File attached/generated from a protected parent has immutable
protection domain/source/purpose, `is_private = 1`, and permission hooks that check
the protected source plus the File on read/download/copy/retarget/delete/share.
Existing public Files are inventoried, physically moved to private storage with
URLs/references updated under lock, and old public paths revoked before activation.
Communication attachment APIs verify read authority on each source File before
copying by File ID. Recipient artifacts use short-lived value-bound purpose tokens
or direct email bytes, never a public File URL or generic document key.

Protection also applies to the physical blob/hash group. Protected and
unprotected File rows may never share one storage URL even when content hashes
match. Upload/privacy/content/optimization/retarget/delete locks every File row in
the old/new hash or URL group before disk mutation; protected upload uses opaque
private isolated storage and bypasses cross-domain deduplication, while an
unprotected mutation encountering a protected group clones on write or fails.
File controller guards plus post-helper reconciliation cover core raw attach/
relink/privacy helpers and roll back a parent operation on domain mismatch. New
protected-capable uploads use a private staging service. Activation splits mixed
groups and verifies no protected File shares a physical URL or mutable blob.

Data Import is source-derived protected staging, not a System Manager escape.
When `reference_doctype` can create/update protected rows, the Data Import parent,
upload File, preview/warnings, background job, and every Data Import Log inherit
the strongest target domain and require matching raw/write authority. Protected
imports use isolated private staging and reject public Google Sheets. A cooperative
`DataImportLog.db_insert` interceptor classifies/minimizes row names, messages, and
exceptions before SQL; list/status/log/file/retention APIs recheck the parent and
target. Existing staging/logs are inventoried and minimized before activation.

Protected Communication, Communication Link, Email Queue, Comment, Notification
Log, and mention records carry the highest applicable protection domain and one
audited primary source. Automatic Dynamic-Link timeline fan-out is suppressed:
one artifact may link to several records only when the creator and every viewer
have raw access to every target in the same domain; otherwise the service creates
separate snapshot-based correspondence records. Timeline/list/report/export/REST
permission checks revalidate the primary source, all links, recipients, and
attachments. Mentions are rejected unless each recipient can read the protected
parent and comment; no notification may contain a hidden title/content/link.
Existing communications/comments/files/queues/notifications are classified and
conflicting fan-out is unlinked or split with immutable audit before activation.

Core Document Follow is forbidden for protected targets; creation/RPC guards
check the target, activation removes existing follows, and scheduled follow mail
cannot query/email protected Version or Comment content. Protected Comment/
Communication handlers keep the parent's denormalized `_comments` empty, and
generic optional-column/list APIs may not select it. Protected assignment uses a
source-aware service: the assignee must already have target access, core auto-share
and auto-follow are disabled, and ToDo/Notification descriptions contain only a
constant non-PII action label plus opaque authorized link. Existing free-text
protected assignments/follows are scrubbed or revoked before activation.

Operational diagnostics are protected artifacts too. NPO jobs enqueue only an
opaque Deferred Work/diagnostic ID, model version, and idempotency key; protected
arguments and payload stay in restricted storage. Core Error Log, RQ Job, and
Scheduled Job Log receive only a generic code/incident ID after write-time
sanitization, while raw traceback/context is stored in restricted `NPO Protected
Diagnostic` under the identity/accounting domain (or dropped if safe storage
fails). Virtual RQ list/load/count, scheduler-log update, Error Log deferred insert,
and direct diagnostic reads enforce the conjunction. Existing logs/Redis failure
registries are scrubbed before activation and terminal diagnostics follow explicit
retention.

Submission Queue inherits the submitted document's protection domain. Protected
background submit/workflow paths enqueue only an opaque operation/reference/
version key, never the in-memory Document; the worker reloads it under current
authority, control permits, source locks, and fingerprint. Exceptions store only a
protected incident ID. Queue list/status/error/unlock/retry and retention cleanup
recheck the referenced document/domain, cannot expose names or traceback, and
retain the required replay tombstone after payload minimization. Permission/model
changes between enqueue and execution fail closed.

Sanitization occurs before any external/log sink. Every protected request/job runs
inside a protection-domain context that installs a Sentry `before_send` filter (or
suppresses capture), removes request/form/JSON, headers, local variables, and raw
exception text, and emits only incident ID/generic code. Worker exception wrappers
similarly prevent raw traceback/arguments from stdout, bench/file logs, Redis job
failure text, and scheduler logs before storing the restricted diagnostic. A sink
whose effective pre-send/pre-write control cannot be verified blocks activation;
post-Error-Log scrubbing is not treated as containment.

Ancillary Desk/web artifacts follow the same source rule. Protected targets reject
generic Tag/Tag Link creation and tag RPCs return no title/name without target
permission. Access Log, View Log, Route History, API Request Log, and report HTML/
filters are minimized before write to opaque source/incident IDs. Provider
Integration Request is domain-protected; credentials/headers are redacted or
encrypted and payload/evidence access uses the accounting conjunction. `_seen` and
`_liked_by` never contain unauthorized users and are omitted from generic output.
Email-read pixels use a short-lived purpose-bound token and protected service
update instead of direct `db.set_value`; expired/foreign tokens reveal and mutate
nothing. Existing rows are classified/minimized during activation.

Child-table Link values are not independently protected by Frappe field permlevel,
and a direct generic child-table list can check only the parent DocType instead of
the permitted parent row. Raw Household and Household-scoped Membership access
therefore uses an all-or-nothing rule: `has_permission` and list query conditions
deny the whole parent unless the caller can read every current/historical linked
Contact, Member, and other exposed target. Permission-query and named-read hooks
on every parent-only registry entry deny direct generic list/report/export/REST
reads for custom identity/financial children; shared ERPNext children exclude any
row whose persisted parent is NPO-purpose. Trusted server code uses permission-
bypassing internal reads only after it has checked and locked the parent. Child
data reaches a client only as part of an authorized parent load or through a
separate permission-filtered summary API.
That API returns only authorized display projections, with no hidden row IDs or
counts; it never serializes the raw parent and then removes fields client-side.

Raw access is granted only to roles with global read on the required target
DocTypes; partially scoped users receive the summary API, not raw DocPerm. Sharing
is prohibited for Household and for Household-scoped Membership: DocShare
insert/update hooks reject it, activation removes/blocks existing shares, and
permission queries never rely on a condition that Frappe's later DocShare OR can
bypass. Membership `scope` is immutable after insert, so an already shared
Individual/Organization Membership cannot race a later conversion to Household;
every DocShare insert/update/retarget affecting Household or Membership locks all
old/new target parents in deterministic doctype/name order and rechecks the
persisted target and current Membership scope. Pure unshare/trash only removes
access: it does not acquire a parent mutex after Frappe has locked DocShare, and is
idempotent if migration already removed the row. The fenced migration-only
conversion takes the Membership mutex first, then locks/removes its DocShare rows
before changing scope. Thus a share that starts first commits before the migration
removes it, while a share that starts second observes Household scope and fails;
concurrent native unsharing cannot invert the lock order. `DocShare` itself is in
the protected `_save`/`before_discard` registry, so forged or canonical discard
cannot skip these hooks. Individual/Organization Membership sharing remains
subject to its normal target-safe policy.

Exact PII matching is deduplication evidence, not proof that a guest controls an
existing identity. An unauthenticated signup/donation may reuse or mutate an
active Contact/Member/Customer only after an authenticated portal/session claim
or a single-use verification sent to an existing canonical endpoint that is
classified Personal and unique among active Person Contacts. A Shared/Unknown
endpoint, an address linked to multiple people, or a Generic Endpoint Contact
proves control of the mailbox only; it requires an already bound session plus an
independent personal factor, or staff review, before selecting a person. Otherwise
create a restricted, expiring `NPO Identity Claim` and return the same opaque
response whether zero, one, or several candidates exist; no role, billing,
correspondence, or accounting projection is attached until proof and a locked
recheck succeed. Verification tokens are random, single-use, rate-limited, stored
only as hashes, and sent only to the canonical endpoint; claim logs exclude the
token. New identified records also require endpoint proof or staff
review. Explicit anonymous choice follows the separate Anonymous System path;
failed/ambiguous proof never falls back to it.

Frappe's generic Personal Data Download/Deletion workflows are fenced for every
NPO-managed subject. Email equality is not a stable subject selector: shared or
reused mailboxes must never export/anonymize all matching Contacts. Public forms
may only open an opaque `NPO Privacy Request` after the same endpoint proof above;
they cannot invoke core user-data hooks directly. The request binds one immutable
canonical subject key, verified claimant/session, jurisdiction/purpose, retention
snapshot, status, operation ID, and audit. A download service locks/rechecks that
subject and produces an allowlisted, permission/relationship-aware private export
that excludes other Household people, shared-endpoint owners, secrets, and legally
retained third-party/accounting evidence. Deletion/anonymization locks the subject,
roles, projections, endpoints, and dependencies, applies the retention matrix,
never uses forced rename/raw SQL, and detaches only that subject's endpoint claim.

Overrides/extensions for Personal Data Download Request, Personal Data Deletion
Request, their guest methods, scheduled processors, `get_user_data`, and installed
`user_data_fields` hooks reject NPO-managed matches and route to this service.
Queued/existing requests are inventoried before activation. Shared-mailbox,
multi-Contact, alias, Household, portal User, accounting-retention, and concurrent
request tests prove one verified stable subject per export/anonymization. The
privacy-request methods/hook registry and source hashes are activation
capabilities.

| Operation or data | Required access |
|---|---|
| Read ordinary Member/Membership fields | Existing Non Profit role permissions; no automatic Contact/Customer read grant |
| Read canonical Contact/alias fields on Member, Donor, Volunteer | `Non Profit Manager` plus normal Contact read, or `System Manager`; presentation APIs return only approved display snapshots |
| Create/link a person role in Desk | Create on role plus write on selected Contact and Customer, matching current helper policy |
| Public signup/donation | Guest never selects an identity by ID; exact matching reveals nothing and cannot mutate an existing identity until session/email-control proof succeeds, otherwise an expiring restricted claim awaits verification/review |
| Raw NPO Identity Claim | System service and `System Manager`; claimant may consume a signed one-time token but cannot read candidate IDs, evidence, or another claim |
| Personal-data request/export/anonymization | Claimant receives only a verified-subject allowlisted export; raw request/evidence and execution require the privacy service plus `System Manager`, and accounting deletion decisions also require the accounting conjunction |
| Read/edit raw Household, people, and addresses | `Non Profit Manager` plus read/write on every exposed current/historical Member/Contact/Address target; otherwise deny the whole raw parent and use only the filtered summary API |
| Create/link Household Customer, Donor, Bank Account, or joint ask | `Non Profit Manager` plus write on Household and normal create/write access to every affected accounting/domain record; submitted accounting also requires the applicable Accounts role |
| Select receipt jurisdiction/language on a draft | `Non Profit Manager` plus write on the Donation Receipt; selection must have a current provider/template and becomes immutable on submit. Corrections inherit the original and cannot select another jurisdiction |
| Activate/change a jurisdiction provider or template manifest | `Administrator` or `System Manager` under capability audit; affects future drafts only and cannot reinterpret issued receipts |
| Redacted identity migration report | `Non Profit Manager` or `System Manager`; rows are permission-filtered and reveal no inaccessible source identifiers |
| Raw identity migration issues/evidence and `identity` activation row | `Administrator` or `System Manager` |
| Raw Donation-accounting evidence, `donation-accounting` activation row, cutover execution, and audit | `Administrator`, or a user holding both `System Manager` and `Accounts Manager` |
| Enable/change NPO Membership Accounting Configuration | `Administrator`, or both `System Manager` and `Accounts Manager`, plus normal write on the affected Company/accounts |
| Enable/change NPO Donation Accounting Configuration | `Administrator`, or both `System Manager` and `Accounts Manager`, plus normal write on the affected Company/Item/accounts/tax setup |
| Propose organization evidence or operating-unit link | `Non Profit Manager` plus read/write on every affected NPO Organization, Customer, Supplier, and source-evidence record |
| Verify, revoke, or transfer organization key | `System Manager`; accounting-master relinking also requires normal write access to every affected Customer/Supplier and an immutable approval audit |
| Consolidate/split Contact or role | `System Manager` or `Non Profit Manager` plus write on every affected record |
| Archive/merge Customer or Supplier with accounting history | `Administrator`, or both `System Manager` and `Accounts Manager`, plus normal write on every affected accounting master |
| Read raw migration/audit result | Identity uses the identity rule above; accounting uses the accounting conjunction above. Immutable audit contains IDs/evidence, never credentials or secret portal tokens |

`ignore_permissions=True` is limited to reviewed migration/system services after
the outer operation has established authority and scope. It is never used to let
a caller name arbitrary Contact, Customer, Supplier, Household, Member, or Donor
records. Tests cover permission-aware lists, direct document reads, Link search,
guest ambiguity, and redaction.

Frappe combines role DocPerm grants with OR. The exact predicates are
`Administrator OR System Manager` for identity control and `Administrator OR
(System Manager AND Accounts Manager)` for accounting control. Enforce them
explicitly in `has_permission`,
`permission_query_conditions`, controller mutation guards, and every whitelisted
service; DocPerm alone is insufficient. The same rules cover form, list, report,
direct document load, and REST/RPC access.

## 13. Optional Good Connector Integration

`non_profit` remains installable with ERPNext alone. It owns all required schema,
matching rules, locks, aliases, migration state, and validation described by this
proposal.

When Good Connector is installed, `non_profit` may use it for:

- normalized exact-match candidate searches;
- fuzzy duplicate suggestions and staff review queues;
- bulk duplicate-scan suppression and one deduplicated reconciliation job after
  the complete migration run succeeds;
- Good Connector's integration-owned QRR, EBICS, Bank Transaction, and CAPTCHA
  transport capabilities already covered by optional contracts; Swiss use policy
  is supplied by `good_npo`.
- the post-selection transactional payment-materializer hook for Customer-model
  On Receipt Donations; candidate discovery remains side-effect-free and Good
  Connector retains locking, Payment Entry submission, and Bank Transaction
  linking ownership.

Optional integration may produce more review candidates, but it must not change
hard uniqueness, subject-type validation, canonical selection, accounting party,
or migration activation results. Ambiguity always fails closed in the required
`non_profit` service.

This optional identity/accounting dependency does not weaken the existing public
donation CAPTCHA contract: guest donation remains fail-closed when Good Connector
or its configured CAPTCHA service is unavailable. Desk/manual identity and
accounting services remain functional with ERPNext and `non_profit` alone.

Existing MiKi-owned `Customer.business_uid`, `Customer.legal_form`, and
`Supplier.legal_form` remain owned by MiKi. `non_profit` may read validated UID
as optional organization evidence only through a versioned provider hook such as
`non_profit_organization_identity_evidence_provider`; it does not recreate,
rename, transfer, require, or import the owner of those fields. Provider results
are claims until explicit verification, and provider lifecycle changes invalidate
the migration fingerprint. Generic legal-field ownership, if ever needed,
requires a separate cross-app decision.

For canonical `CH_UID` verification, that evidence is evaluated only by the Good
NPO Switzerland provider. On a site without `good_npo`, MiKi values remain
preserved claims/review evidence and do not activate a country-specific base rule.

### 13.1 Required consumer adapters

The implementation release updates these current cross-app contracts atomically;
strict activation is blocked while any installed consumer still uses the old
behavior.

- **Good NPO public continuation:** existing donation/signup endpoints keep their
  route and purpose-specific payload contract, but an unverified identified guest
  receives opaque `verification_required` instead of an immediate checkout or
  created Membership. NPO Identity Claim stores purpose (`donation_checkout` or
  `membership_signup`), normalized protected payload, expiry, and unique client
  idempotency key. After endpoint proof, Good NPO consumes it under lock exactly
  once and runs the current creation transaction; Donation returns the normal
  checkout payload and Membership creates/reuses role/Membership then persists
  durable invoice/confirmation work. Explicit anonymous donation remains separate
  and ambiguity never falls back to it. Current Good NPO/native donate requirements
  must deliberately adopt this two-stage response.
- **Good NPO Switzerland policy:** `good_npo` registers the sole V1 receipt policy
  for jurisdiction `Switzerland` and the `CH_UID` organization-identifier provider.
  The receipt policy decides legal entitlement, Household joint recipient approval,
  fiscal-period issue rules, numbering, correction/reversal form, rendering, and
  notification from base qualification facts. Original, Correction, and Correction
  Reversal each have separately approved versioned DE/FR/IT templates; missing
  language/template fails without German fallback. A finalized post-receipt refund
  creates one separately numbered negative correction referencing the original and
  sends it automatically to the frozen donor recipient; refund undo creates the
  reversing correction. No authority-notification workflow is created. Existing
  German-law `Donation Receipt DE` remains a legacy renderer and is never selected
  as Swiss output.
- **Good NPO Swiss payment presentation:** `good_npo` decides whether a Swiss
  Donation/Membership flow displays a QR bill or requests a QRR. Good Connector
  remains the technical owner of QR-IBAN validation, QRR generation/storage/
  collision, EBICS ingestion, and Bank Transaction matching. `non_profit` exposes
  only generic owner/lifecycle hooks and its ERPNext-only manual reference; neither
  transport app decides receipt entitlement or organization identity law.
- **Native Membership website session:** `Membership.create_member_from_website_user`
  delegates to a base stable-subject service and never selects `Member.email_id` or
  inserts a Contact-less Member with `ignore_permissions`. The authenticated
  Website User locks one explicit User-to-canonical-Person binding; an active bound
  subject creates/reuses one Individual Member idempotently. A missing binding
  pauses behind the same opaque endpoint-proof Identity Claim or staff review;
  shared/ambiguous email never chooses a person, and Organization membership uses
  its explicit staff/Good NPO flow. Migration adopts only deterministic
  User/Contact portal relationships, inventories every Membership Web Form and
  external caller, and blocks strict activation while the legacy first-email path
  or unresolved binding remains.
- **Good NPO membership billing:** Individual/Organization Subscription and direct
  Membership invoices use base purpose `Membership Subscription` with immutable
  Membership, Subscription where applicable, and globally unique billing-cycle/
  attempt owner keys; Credit Notes use `Membership Subscription Reversal` and the
  exact source-row/reversal matrix. Existing `good_npo_membership` remains a
  compatibility mirror, never the only owner. First billing, renewal, Payrexx
  settlement, cancellation/refund, and retry use focused base services. Migration
  adopts each existing invoice deterministically or blocks activation as orphaned/
  ambiguous. MiKi and every generic invoice consumer exclude/route both purposes.
- **Good Event public continuation:** when identity enforcement is active, an
  identified guest attendee also pauses behind an opaque, purpose-bound,
  idempotent NPO Identity Claim. Canonical-endpoint proof resumes the exact
  capacity/booking transaction once and binds the returned canonical Contact
  explicitly. Before proof, registration and correspondence neither reuse nor
  mutate an existing Contact/Customer nor select a Contact by email. Provider-
  absent standalone behavior remains available only when no managed identity is
  involved; current Good Event booking/correspondence requirements adopt this
  continuation before activation.
- **Payrexx events:** extend the existing authenticated settlement-source provider
  contract with provider status, transaction/event/refund/dispute ID, amount,
  currency, and provider timestamp. Payrexx keeps webhook authentication,
  Integration Request locking/retrieval, and immutable evidence; the NPO adapter
  returns `applied`, `duplicate`, or `review`. Confirmation invokes Intent capture/
  settlement, while NPO-owned refunded/chargeback events with stable keys invoke
  Refund Instruction. Missing/ambiguous evidence enters review. Generic non-NPO
  behavior may continue ignoring refunds, but callback-capable NPO checkouts are
  adopted before activation and may not use that fallback.
- **MiKi final-submit writeback:** `miki_declaration_writeback` is a named protected
  operation. MiKi retains declaration rules, snapshots, shared-Contact splitting,
  and field semantics; non_profit supplies target locks, expected-version/
  canonical-anchor checks, field/record allowlist, operation sentinel, and audit
  for only the declaration's snapshotted Customers, Contacts, Addresses, portal
  User, and Change Log. Conflict-free final submit remains one transaction. Stale
  targets, identity conflicts, or a changed login email remain pending/reviewable;
  the latter completes only after endpoint proof.
- **Good Connector portal subject:** retain JWT routes/wire payloads but delegate
  every legacy `getdata`/listing/`getcontact`/`putcontact`/`getaccount`/
  `putaccount`/`changeemail` action and `checktoken`/`checktokenlogin` language
  resolution through optional
  `good_connector_portal_subject_provider`, registered by non_profit without
  reverse dependency. For an NPO identity/account action, the resolver maps JWT
  User to exactly one immutable Person or Organization subject through explicit
  User/Portal User relationships, checks each requested Contact/Customer/role, and
  never selects all email matches or the first Customer. A registered app-scoped
  principal may authorize only its declared non-NPO actions and cannot pass this
  Contact/Customer path. Ambiguous/missing/shared bindings fail closed without
  IDs/counts.
  Email change additionally verifies the new endpoint, then atomically updates
  that User, one canonical Contact endpoint, applicable Portal User rows, and
  token/claim state. Without a provider, fallback is allowed only for one enabled
  User plus one explicit Personal Contact/Customer relationship. Migration builds
  bindings from explicit portal relationships and records conflicts for review;
  current Good Connector auth/portal requirements must adopt this resolver.
- **MoPi workforce principal:** Good Connector passes immutable app/action context
  to the portal-subject provider. MoPi may register an app-scoped User-only
  workforce principal for an enabled hub User that deliberately has no Contact or
  Customer. It preserves User-keyed task/completion/upload/certificate ownership,
  never satisfies an NPO Person/Organization role, and grants no Contact/Customer
  or other-app authority. Migration records the explicit User/MoPi binding and
  fails closed on missing/conflicting app scope; disabled users are rejected.
- **Barakah Supplier portal principal:** stable-principal resolution runs before
  Barakah's custom Good Connector dispatcher. An enabled JWT User maps through
  explicit Portal User evidence to one app-scoped principal with an allowlisted
  Supplier set; one User may intentionally serve multiple reviewed Suppliers, but
  every task/file/order target is checked against that persisted set. The handler
  receives the exact User/principal and never re-expands email to Users, Suppliers,
  Contacts, or Customers. Supplier-only users remain valid and create no Customer;
  generic/shared Contacts confer no authority. Migration records multi-Supplier
  conflicts/review, and missing/disabled/forged/cross-app bindings fail closed.
- **Good Demo reset:** automatic reset is allowed only on a durably enrolled
  disposable site with developer/demo mode, approved baseline export, and no real
  provider/EBICS/Bank Transaction/unmarked evidence. `good_demo_reset` fences
  identity/accounting, disables demo users, locks and verifies the complete marked
  graph, then performs all-or-nothing controlled cancellation/deletion and seed
  replay; a non-resettable audit remains. Mixed ownership fails without partial
  deletion. Unenrolled sites lose the daily physical-reset behavior.
- **Consumer cleanup operations:** `ilanga_people_cleanup`,
  `good_event_hosted_qa_cleanup`, `good_event_test_data_reset`, and
  `miki_hosted_qa_cleanup` are named protected operations. Each requires explicit
  disposable/test-site enrollment, a complete graph fingerprint, deterministic
  locks, durable audit, and protected-artifact cleanup permits. Only unused drafts
  may be physically deleted; protected identity history archives or detaches, and
  accounting is cancelled/reversed while required tombstones remain. No operation
  raw-deletes Email Queue, protected children, or retained evidence. Good Event
  keeps an independent legacy cleanup fallback only where the non_profit model is
  not active.
- **Consumer retention operations:** `good_connector_log_retention`,
  `good_connector_failed_email_cleanup`, and `good_demo_user_retention` are
  versioned named operations/jobs. Each classifies every Integration Request/log/
  Communication/Dynamic Link/User/Contact artifact by source before mutation.
  Protected rows use audited minimization, key erasure, and replay-safe tombstones;
  only proven unprotected rows retain physical pruning. Demo purge requires an
  enrolled explicitly bound demo-subject graph, never expands by shared email, and
  commits each User graph atomically with durable audit. Stale job versions and
  mixed/unmarked ownership fail closed.
- **Goodvantage File/DocShare composition:** when `goodvantage_app` is installed,
  its receipt-source File extension/permission hooks and DocShare validator compose
  with the NPO protected-artifact perimeter as an intersection. Both File mixins
  call `super()` and are verified in either effective MRO order; permission-query
  conditions are AND-composed rather than last-wins/OR. Receipt-source plus NPO-
  protected Files require both policies, NPO-only and receipt-only Files require
  their applicable policy, and unrelated Files retain core behavior. Create/list/
  read/download/copy/old-new retarget/delete/share and DocShare validation classify
  every persisted/requested source. Hook/MRO/query hashes and a versioned
  composition capability block activation on drift without either app importing
  the other.
- **Good Event customer classification:** organization search accepts Company and
  Partnership. When NPO fields exist, managed organization bookings require
  `npo_subject_type = "Organization"`; unmarked ERPNext Company/Partnership remains
  valid. An optional person-Customer provider resolves the canonical Person
  Customer. Standalone fallback never reuses a Household, Organization, Anonymous
  System, or conflicting managed Individual merely because it shares Contact/core
  type. Historical bookings/invoices are not retargeted; conflicting open drafts
  enter review.
- **Good MEL identity and compliance:** an optional Good MEL provider resolves
  provisioning under staff authority to one explicit User, canonical Contact, and
  Partner organization without adopting email-selected aliases. Subject Access,
  anonymization, disposal, and legal-hold rows store one immutable canonical
  subject key and use the protected artifact/retention service; no operation
  expands from a shared email. Migration maps existing `subject_user` rows,
  preserves source evidence, and blocks ambiguous/unmapped cases for review.
- **Ilanga institutional importer:** each deterministic foundation source key calls
  the base organization projection service and receives NPO Organization,
  operating Company/Partnership Customer, and Organization Donor. The Ilanga SHA-1
  remains provenance, never verified legal identity. Representatives become
  Person Contacts; foundation mailboxes remain Generic/Unknown communication
  endpoints. Reruns use manifest/source key and canonical links. Cleanup returns
  delete/archive/preserve/blocked; only unused pre-activation source-owned test
  graphs delete, while protected history archives or detaches. Existing
  `ilanga_legacy_id` rows are classified/mapped without merging ambiguity.
- **Fundraising facts and analytics:** non_profit exposes one read-model fact per
  immutable Donation lineage root: Donor, campaign/dimensions, gift date, intended,
  received, refunded, net recognized, and qualification state. Counts/RFM
  frequency/cohorts count distinct qualifying roots; recency uses root gift date;
  revenue/RFM monetary/Pareto use net recognized; average gift divides that amount
  by qualifying roots. Partial receipts and continuations remain one gift, refunds
  reduce recognition, and accounting reports retain posting-period authority.
  Good Analytics bases become `Recognized` and `Intent`; current unpaid=false maps
  to Recognized, unpaid=true to clearly labelled Intent. Good NPO totals use the
  same Recognized facts.
  The formulas are fixed: `gift_date` is the immutable root Donation date;
  `intended` is root `lineage_intended_amount`, updated only by a controlled
  amendment and never reset to a continuation's remaining amount; `received` is
  the sum of distinct confirmed root Economic Receipt inflows before refunds/
  chargebacks (held and excess are separately flagged); `refunded` is terminal
  cash Refund/Chargeback Instruction outflow; `net_cash_retained = received -
  refunded`; and `net_recognized` is signed submitted Donation-purpose charge/
  Credit Note effective payable, excluding held/released excess and including
  applied/standalone reductions exactly once. Retained credit reduces recognition
  when its Credit Note posts; later Credit Application changes neither recognition
  nor gift count. `qualification_state` is Recognized when net recognized is
  positive, Intent when active intended value exists without recognition,
  Held/Review when only unresolved cash exists, and Fully Refunded/Cancelled when
  terminal with no positive recognition. Customer-model vouchers outrank legacy
  evidence; legacy submitted ledger interpretation outranks Reviewed Legacy Manual
  Evidence; `Donation.paid`/amount never overrides either after activation. The
  fact materializer stores source fingerprint/formula version and must reconcile
  to root vouchers/evidence before publication.
- **Newsletter audience identity:** NPO-derived Good Analytics and MiKi providers
  emit a versioned audience projection containing immutable canonical subject,
  verified endpoint key/version, delivery-purpose eligibility, consent/source
  provenance, and snapshot version. New outreach never falls back to
  `Donation.email` or an unproven raw Email Group. Audience synchronization
  inactivates removed/revoked/reassigned endpoints for future queueing instead of
  remaining additive; split/consolidation/archive/revocation changes eligibility
  without rewriting Consent Log or historical campaign/Recipient snapshots.
  Good Newsletter checks current endpoint/purpose eligibility immediately before
  queue/send, while Subscriber, Consent Log, Recipient, and delivery events join
  the protected consolidation/privacy/retention graph.
- **Settlement acknowledgement:** a versioned `acknowledgement_qualified`
  predicate derives only from immutable lineage-root fundraising facts. It becomes
  true when confirmed, accepted net cash allocated or reclassified to recognized
  gift income first meets the configured policy threshold (default: one positive
  Company-currency minor unit). An unpaid pledge receivable, Held cash, Excess
  Pending, released Customer credit, unaccepted/void receipt, or recognition-only
  Credit Note state never qualifies. The materializer persists the first
  qualifying Economic Receipt/event/root and policy version and emits one stable-
  key Accounting Outbox/work item. Later partial/full refund, chargeback, or
  recollection does not emit another acknowledgement unless a future explicitly
  versioned policy defines a distinct key. Good NPO consumes it without reading
  `Donation.paid` and preserves the
  existing `thank_you_sent*` idempotency/audit fields. `on_payment_authorized`
  remains a model-dispatching compatibility facade, not Customer-model settlement
  authority. Under Active accounting, Good Demo checkout, seed, and refill use the
  Customer-model Intent/settlement service; every voucher must reconcile to the
  same fact and acknowledgement materializer.
- **Base accounting navigation:** non_profit owns permission-aware
  `get_role_accounting_targets(role_doctype, role_name, company)` for Member and
  Donor. It derives distinct immutable historical parties from Donation/
  Membership/Subscription/voucher/open-item evidence plus the future canonical
  Customer, labelled by regime and open-item state, never merely the role's current
  Customer. Base `donor.js` and `member.js` and Good NPO all consume it. One target
  opens the standard report directly; mixed history shows separate Legacy Member/
  Donor and Customer ledger/receivable actions. No synthetic combined ERPNext
  ledger or historical repointing is introduced.

Schema, API, and installed-behavior changes require coordinated version decisions
under the custom-app versioning policy. Documentation-only edits to this
unaccepted proposal do not themselves bump a package version.

## 14. Affected Apps

| App | Expected impact |
|---|---|
| non_profit | Owns jurisdiction-neutral shared roles, Household, identity/accounting rules, receipt qualification facts/claims/correction lineage/provider interfaces, fundraising facts, and mixed-regime navigation; ships no Swiss legal policy, template, UID, QRR, or QR-bill default |
| good_npo | Owns Switzerland V1 receipt entitlement/corrections/numbering/notification, approved DE/FR/IT templates, CH_UID verification, Swiss QR presentation policy, plus public continuation, membership ownership, Household inheritance, acknowledgements, and navigation |
| miki_app | Keeps the organization contract and declaration flow through named protected final-submit writeback; restores Partnership, excludes every NPO-purpose invoice from generic hooks, emits canonical newsletter subjects/endpoints, and routes hosted-QA cleanup through its named operation |
| ilanga_app | Replace shared-couple behavior and route institutional import and both institutional/people cleanup through Household/organization protected services |
| good_analytics | Consume lineage-root Recognized/Intent facts instead of Donation row/paid aggregation and emit canonical newsletter subjects/endpoints without Donation-email fallback |
| good_demo | Enrolled disposable-site all-or-nothing protected reset; Customer-model checkout/seed/refill, acknowledgement-compatible fixtures, and bound-subject retention |
| good_event | Verified guest continuation, optional membership/person provider, Organization-aware Company/Partnership selection, and enrolled hosted-QA/test-data cleanup |
| good_connector | Optional matching/materializer and Swiss QR-IBAN/QRR/EBICS transport mechanics, plus stable-subject portal/action/token-language provider and protected retention/failure cleanup; decides no receipt or identity law |
| mopi_app | App-scoped User-only workforce principal for portal tasks/completions/uploads/certificates without NPO Contact/Customer authority |
| payrexx_integration | Authenticated confirmation/refund/chargeback event adapter for NPO Intents while preserving generic and legacy behavior |
| good_newsletter | Canonical subject plus verified endpoint audience projection, current delivery eligibility, consent/history preservation, and protected retention |
| barakah_app | Exact app-scoped User-to-Supplier-set portal principal before custom dispatch, Supplier-only task/file/order access, and no forced Customer creation |
| good_mel / barakah_mel | Canonical-subject provisioning, Subject Access/legal-hold adapter, and partner-organization compatibility for Customer, Supplier, or both |
| goodvantage_app | Explicit File/DocShare permission/MRO intersection plus global Customer/Supplier, Party Link, and HRMS Payment Entry/doc-event compatibility |

Changes to Member or Membership semantics must update and verify `miki_app` in
the same implementation change.

## 15. Acceptance Criteria

- Creating Member and Donor roles for the same person reuses one canonical
  Contact without creating Customer prematurely.
- The first financial trigger creates or reuses one Person Customer for that
  canonical Contact.
- An Organization Member or Donor reuses one Customer whose `customer_type` is
  Company or Partnership and whose NPO Organization identity is explicit, even
  before financial activity.
- Every active role has a subject type and the required Contact or organization
  Customer; cross-field Customer type and canonical Contact links agree.
- Canonical anchors cannot retarget any existing role/accounting/portal/history;
  native merge/rename is fenced and controlled split/consolidation preserves
  submitted ownership.
- Every person identity anchor is a Contact classified as `Person`; a Generic
  Endpoint or Unclassified Contact cannot satisfy an Individual role,
  accounting projection, Volunteer, or Household Person.
- A canonical Contact cannot identify two Person Customers or two Individual
  Suppliers.
- The same Contact can remain linked as representative to multiple organization
  Customers and Suppliers.
- One organization Customer can hold Member and Donor roles without duplicated
  Contact or Address records.
- One verified organization key identifies at most one active NPO Organization;
  reviewed parent/child operating Customers may share it without being aliases,
  and unidentified organizations remain review-based without a false uniqueness
  claim.
- Changing source UID evidence cannot directly mutate a verified key. The
  versioned provider/review flow locks the legal identity, rejects collisions,
  invalidates stale migration evidence, and cannot leave an orphaned key.
- Every organization Customer/Supplier link has an Active approval for new use or
  Settlement Only approval for historical correction; Revoked has no remaining
  link. Verified-key revocation tombstones the same unique row and controlled
  transfer keeps it Active under the new owner with immutable action history.
- Supplier-only parties remain valid and do not create Customer until a
  receivable-side role requires it.
- NPO-managed scope is explicit; unrelated ERPNext Customers/Suppliers are not
  classified or blocked, while a master linked to an NPO role/projection cannot
  evade validation by clearing the marker.
- Managed Party Link deletion requires controlled unlink/audit; an unmarked core
  Party Link remains outside NPO behavior.
- Exactly one controlled Anonymous System Customer and Donor exist with no
  Contact, Household, organization, communication endpoint, or receipt recipient;
  ambiguous matching never falls back to them.
- Anonymous System parties are absent from ordinary selectors and rejected from
  every non-Donation commercial/membership/payment path.
- Public exact matching never mutates an existing identity without session or
  canonical-endpoint proof; pending claims reveal no candidate existence and
  impersonation attempts create no role/accounting side effect.
- Native Membership Website User save resolves one explicit User-to-Person binding
  or opaque proof/review; it never selects the first Member by email or creates a
  Contact-less role, and legacy Web Form callers block activation until migrated.
- Good Event identified guest registration follows the same opaque proof-and-
  continue contract; it neither adopts/mutates an email match nor selects one for
  correspondence before proof, and resumes capacity/booking exactly once.
- Good Connector portal actions and token-language lookup resolve one explicit
  JWT User-subject relationship; missing/shared/multiple bindings fail without
  first-email/first-Customer selection or hidden candidate metadata.
- Good MEL provisioning, Subject Access, anonymization, disposal, and legal holds
  use one immutable canonical subject key; shared mailboxes cannot broaden a
  request and ambiguous legacy `subject_user` rows block activation.
- Volunteer creation reuses the canonical Contact and creates no Customer unless
  another financial role requires one.
- Volunteer identity does not depend on email, and email changes do not create a
  second Volunteer.
- A Household can include a person with no NPO role.
- One person with Member and Donor roles appears once in a Household.
- A Contact belongs to at most one current financial Household; prior Household
  relationships remain dated history and cannot create current projections, asks,
  Donors, or receipts.
- Household history and current-primary rules remain enforced.
- Generic Contact/Address hydration exposes no reverse Household Dynamic Link.
  The authorized Household loader returns exactly current Household Person and
  Household Address Link rows, while ended rows remain only as history.
- Raw Household/Household-Membership access is denied when any linked target is
  unreadable; the separate summary projection exposes only authorized rows and no
  hidden IDs/counts.
- Household separation changes dated relationships without splitting identity
  or moving historical financial documents.
- Household financial closure has an immutable effective date that blocks all
  new-period direct Desk/API activity, including backdated bypass attempts, while
  controlled historical settlement/correction remains possible.
- Household presence alone never changes the payer or invoice scope.
- Household receives at most one active Customer projection, created only by an
  explicit financial trigger; people retain separate Contacts and Customers.
- Household Membership has explicit scope, dated covered Members, one
  administrative Member included in coverage, and no overlapping same-type
  coverage for one person. Initial coverage intervals fit the corresponding
  Household Person interval and concurrent creation cannot bypass overlap checks.
- Household Membership has explicit payer scope. Household payer uses the
  Household Customer with no billing Member; Covered Member payer uses that
  Member's Person Customer.
- Household Membership rejects subscription-enabled Membership Types and uses
  idempotent Membership Ask cycles for repeat billing. Individual and
  Organization Subscriptions use the Customer matching their Membership subject.
- Family Membership produces one joint ask addressed to Household, while one
  matching `billing_customer` remains the only ledger party.
- Issued joint asks preserve deterministic recipient, salutation, language,
  delivery endpoint, and postal Address snapshots after moves or separation.
- Membership Type collection mode creates a Sales Invoice only for legally owed
  dues; a non-ledger Request never creates false Accounts Receivable.
- Membership Ask accepted amount is the immutable gross payable; explicit
  pricing, taxes, discounts, and rounding produce exactly that final invoice
  total or fail before submission/allocation.
- Request-mode settlement locks one unique Membership Ask cycle, creates at most
  one Sales Invoice at acceptance, aggregates linked Customer advances, and
  allocates them without an artificial overdue interval. It requires configured
  separate advance-liability accounting and Company-currency accounts.
- Invoice and Request Membership Ask modes both reject non-Company currency in
  V1, so accepted amount and ERPNext invoice payable are directly comparable.
- Company-wide advance accounting is explicitly approved only after unrelated
  advance workflows pass compatibility checks; effective setting/account/date
  changes are blocked while a Request ask or reserved/reassignment/refund-pending
  payment depends on them. Issuance and mutation serialize on one Company config
  row.
- Partial, multiple, and excess Request-mode transfers follow the fixed accepted
  amount (equal to requested amount in V1): partial funds remain advances, full funding settles one invoice, and
  excess remains Customer credit/refund review without an implicit discount or
  write-off.
- Membership Ask snapshots immutable Company, currency, party/account, and income
  dimensions; every linked Payment Entry and Sales Invoice must match them.
- Membership cycle roots derive from the immutable unique cycle namespace, not
  Membership name; concurrent namespace backfill/Ask creation cannot collide and
  native Membership/Ask rename remains fenced.
- Request-linked Payment Entries are dedicated and ordinarily immutable, cannot
  be consumed by standard reconciliation before settlement, and use one guarded
  cancel/unreconcile/void lifecycle with no parallel custom allocation ledger.
- Sales Invoice advance discovery and submit-time validation cannot allocate a
  reserved payment to any invoice except its exact owning Ask settlement invoice,
  including automatic, import, REST, and concurrent paths.
- Request acceptance/posting dates derive from the threshold-crossing payment;
  closed periods require Posting Review and a reasoned first-open-date override,
  never job execution day.
- Cancelling a pre-settlement contributing payment recomputes threshold crossing
  under the Ask/payment locks: remaining funded cash selects its own crossing
  date, underfunding clears current acceptance fields until recollection, and
  immutable crossing/reversal history preserves every prior date.
- Expired/abandoned partial asks refund or release real advances without
  cancelling incoming bank receipts. If all pre-settlement payment attempts were
  already cancelled and zero economic receipt remains, Abandon reaches Cancelled
  without a refund/release. Reversed/refunded/released/cancelled attempts may
  create one audited successor under the same cycle root, and valid advances move
  only through controlled reassignment.
- Original Membership Ask invoice links and NPO-purpose markers do not copy to
  Credit Notes; returns resolve their origin through `return_against`/audit links.
- A partner or third party may remit payment without changing the invoice
  Customer; remitter evidence remains attached and ambiguous payments require
  review.
- A verified joint Bank Account links to the Household Customer and may match its
  asks/payments, but does not by itself create joint Donor or receipt entitlement.
- Joint giving uses at most one Household Donor linked to the same Household and
  Customer; Donation accounting, recognition, and receipt recipient remain
  explicit snapshots. The Switzerland provider approves Household Donor plus
  Household Customer as the joint receipt addressee, while personal giving keeps
  individual receipts; base `non_profit` makes no universal legal claim.
- Receipt jurisdiction is selectable before issue and frozen with provider/policy/
  template/language/recipient snapshots. Unsupported jurisdictions remain storable
  but cannot issue/correct; provider changes affect only future drafts.
- Base-only install creates no Switzerland country default, Swiss template/wording,
  CH_UID policy, CHF/language default, QRR, or QR-bill fixture. With `good_npo`,
  Switzerland is the sole V1 provider with approved DE/FR/IT original, correction,
  and reversal output; missing language/template fails without fallback.
- Swiss post-receipt refunds create one separately numbered negative correction per
  finalized refund, automatically sent to the frozen donor recipient; refund undo
  creates the reversing correction and no authority notification is attempted.
- No current inferred household flag is converted to contractual coverage
  without approved evidence.
- NPO-managed Customer/Supplier dual roles use a validated one-to-one Party Link
  and preserve standard ERPNext sales/purchasing behavior; links between two
  unmarked masters retain ordinary ERPNext semantics.
- MiKi campaign and declaration flows continue to require and resolve exactly
  one Organization Member Customer through
  `Membership -> Member -> Customer`.
- MiKi explicitly rejects Household Customer and Household Membership subjects
  at campaign, readiness, declaration, and invoice boundaries.
- MiKi parent Customers remain campaign targets, child Customers remain
  declaration items, and consolidation does not flatten
  `Customer.parent_organization` or promote child-specific memberships.
- MiKi parent/child Customers may share one verified NPO Organization without
  becoming aliases, and MiKi restores ERPNext's Partnership Customer/Supplier
  type option instead of globally removing it.
- MiKi generic invoice, VAT/catalog, delivery, dunning, export, permission, and
  correspondence hooks exclude Donation, Membership Ask, and Membership
  Subscription purpose markers and their reversals/recoveries.
- Contact-only Individual Members remain valid in `non_profit` and ineligible
  for MiKi declarations.
- A Donation uses one immutable accounting model and timing. Legacy Donor Direct
  retains exact historical references; Customer Invoice uses standard
  Donation-linked Sales Invoices and never a direct Customer Payment Entry
  reference to Donation.
- Receivable-on-submit pledges create one standard receivable; On Receipt gifts
  create event-keyed Sales Invoice and Payment Entry vouchers only for confirmed
  funds. Both recognize donation income exactly once and support native Payment
  Ledger reconciliation.
- Each Donation invoice's explicit item/tax/rounding result equals the Accounting
  Event gross accepted amount; pricing rules, discounts, or defaults cannot alter
  it silently.
- Donation event keys are database-unique and source-locked. Excess On Receipt
  funds are not recognized until accepted; unaccepted residual remains standard
  unallocated Customer credit or is refunded.
- One Donation Economic Receipt may have manual/gateway/Bank Transaction source
  aliases but only one root recognition event; cross-source observations reuse or
  enter review, and provider payouts settle clearing rather than donation income.
- Captured-but-unattributed funds post clearing against refundable liability;
  controlled reclassification recognizes accepted income and controlled refund
  clears liability. Base reports held/reclassified/refunded facts; the selected
  jurisdiction provider decides receipt eligibility.
- Original pledge and On Receipt voucher pairs are service-owned and mutation-
  fenced; excess remains reserved until accepted/refunded/released, and Journal
  Entry settlement of Customer-model Donation invoices is prohibited in V1
  except for exact purpose-marked Holding Reclassification or Released-Credit
  Application.
- Donation cancellation/amendment distinguishes enforceable pledge payment
  reversal, pledge release, On Receipt refund, and unaccounted intent. Original
  vouchers stay with the original Donation and Credit Notes/refunds preserve the
  trail.
- After cutover, Legacy Donor Direct permits historical interpretation and
  correction only; old unledgered rows convert/close under the fence and no new
  direct allocation extends legacy accounting.
- Donation Receipt items freeze unique eligible payment allocations, amounts,
  dates, recognition, and recipient snapshots; partial payments may appear in
  different fiscal receipts but no allocation can be receipted twice. Typed
  legacy/manual evidence, claim release/reissue, and negative refund corrections
  preserve old submitted receipts.
- A lineage root emits at most one stable-key acknowledgement work item when its
  versioned immutable-fact qualification first becomes true. Good NPO and Good
  Demo do not use mutable `Donation.paid` as Customer-model settlement authority,
  while legacy `on_payment_authorized` callers continue through the model facade.
- Consolidation provides a dependency preview and never relies on email or name
  as automatic proof.
- Archived accounting aliases remain readable and linked to the canonical
  identity. Settlement Only aliases permit only exact-party settlement and
  correction of pre-archive documents; fully archived aliases receive no new
  roles or transactions.
- Archived role aliases have the same explicit lifecycle, are excluded from
  normal selectors, and cannot consume active uniqueness keys.
- Splitting an identity moves only supported future/unsubmitted relationships;
  submitted accounting remains historically traceable.
- Household separation retains the old Household Customer, Donor, Bank Accounts,
  asks, Donations, receipts, invoices, payments, advances, and credits as the
  historical joint unit; future households receive new projections only when
  needed. It blocks new-period activity at the effective date while allowing
  controlled settlement, corrections, and eligible receipts for historical
  activity.
- Existing submitted Payment Entries, GL Entries, Donations, Sales Invoices,
  Journal Entries, Payment Ledger Entries, Memberships, and Subscriptions remain
  traceable after migration, with required historical Party Type records kept.
- Household schema replacement is blocked unless deployed-site preflight proves
  no Household data, `Customer.household` values, role links, direct Contact
  links, or Household Addresses exist; otherwise verified conversion is
  mandatory.
- Good Demo reset and the named Ilanga, Good Event, and MiKi cleanup/QA operations
  run only on enrolled disposable/test sites with complete locked graph evidence;
  they preserve protected history/tombstones and never bypass artifact cleanup via
  force-delete or raw child/Email Queue deletion.
- `non_profit` owns every required canonical identity invariant and remains
  correct without Good Connector; optional integration never changes the chosen
  canonical record or validation result.
- Good Connector candidate discovery remains side-effect-free; its post-lock
  path holds identity/donation/Company-configuration permits through commit, and
  the transactional materializer creates the Donation invoice, then Good Connector
  submits the Payment Entry and Bank Transaction link with all-or-nothing
  rollback.
- Membership Ask has an ERPNext-only unique reference and focused manual Payment
  Entry service; jurisdiction/provider-owned external references and automatic
  bank matching are optional enhancements.
- Ambiguous identities enter manual review; no migration silently chooses the
  first matching Customer, Contact, Member, or Donor.
- Direct canonical Contact fields, managed Dynamic Link projections, and
  canonical Address ownership agree after migration; legacy links are not
  removed before equivalent target links are verified.
- Contact validation merges compatible duplicate-link provenance before core
  dedupe and rejects conflicting NPO/MiKi metadata rather than dropping it.
- A persisted migration run proves source/target counts, fingerprints, zero
  blocking issues, and the active model version before enforcement can turn on.
- The activation capability manifest matches the exact installed app versions,
  hooks/providers, required fields, and effective MRO; relevant drift suspends
  writers until explicit re-verification.
- Activation uses durable normal-DocType control rows and a resumable write-fence
  and DDL manifest. A post-DDL failure stays Recovery Required and fixes forward;
  Active cannot silently revert to Compatibility.
- Donation and Membership accounting cannot activate or write unless identity is
  Active under the same epoch/migration/capability evidence; identity fencing
  atomically fences every dependent financial control first.
- An organization projection with history has a valid Settlement Only approval
  state. Revoked means zero-dependency unlink, while controlled legal-organization
  consolidation is the only projection-retarget exception and leaves no active
  projection on the alias.
- Membership Type collection mode migration never defaults unknown legal policy;
  null blocks new asks, and effective-dated changes affect future cycle roots only.
- Membership Ask no-cash reductions derive Reduced states and never masquerade as
  funding, settlement, or refund.
- Every NPO-purpose invoice uses frozen posting/date/time, source-row return links,
  and representable effective quantity precision after all ERPNext defaults/
  mappers run. Positive charge/recovery invoices have one explicit non-discounted
  schedule; Credit Notes have core-compatible empty terms/schedule.
- Donation timing is service-derived from one Active Company policy; guest input
  cannot create a pledge receivable, and referenced policy/master drift fences all
  dependent open work.
- Refund recovery restores an unpaid collectible reduction without invented cash,
  but On Receipt/cash/advance/excess/Holding recovery waits for confirmed cash and
  follows its original accounting disposition; retained credit has explicit
  consumed/unconsumed treatment.
- Strict sites have available authenticated external epoch, payload-key, and
  erasure-journal providers plus the mandatory manifested backup/restore/start
  shim. Old backups cannot lower the model epoch, restore anonymized database PII/
  credentials or a destroyed key, or republish an erased file path before backend/
  static service. Protected-history
  sites cannot be cloned into a new incarnation; same-site disaster recovery uses
  one coherently manifested quarantined restore and externally fences the prior
  runtime before promotion; test/successor sites receive attested default-deny
  redacted exports.
- Good NPO Membership Subscription invoices have one base purpose/cycle owner and
  immutable effective billing-input fingerprint;
  MoPi's User-only and Barakah's Supplier-set principals are app-scoped; newsletter
  delivery uses a current canonical subject/verified endpoint; consumer retention
  never fans out by email.
- Goodvantage receipt-source and NPO File/DocShare restrictions compose as a
  permission intersection in either app order without changing unrelated Files.
- Current helper/API paths remain functional adapters until their telemetry and
  release-cycle removal gates are satisfied.

## 16. Verification Matrix

No phase is complete based only on unit tests or acceptance prose. The
implementation release must publish and pass this matrix before per-site
activation.

### 16.1 Install, upgrade, and migration

- Clean install with ERPNext and `non_profit` only.
- Base-only clean install has a generic jurisdiction selector but no country
  default/provider, Swiss template/UID/QRR/QR-bill fixture, and cannot issue a legal
  Donation Receipt. Installing `good_npo` registers only Switzerland V1.
- Clean install with ERPNext, optional Good Connector, `non_profit`, and each
  direct consumer.
- Upgrade the current `non_profit` model both with Good Connector absent and with
  it installed; required identity outcomes must match.
- Upgrade sites containing B2C Contact-only Members, B2B organization Members,
  Donors with/without Customer, duplicate Dynamic Links, role-linked Addresses,
  disabled accounting parties, and ambiguous identities.
- Receipt migration distinguishes explicit country evidence from inherited
  Switzerland defaults, preserves issued renderer/template/language snapshots and
  stored QRRs, keeps German-law `Donation Receipt DE` legacy-only, and transfers
  future Swiss policy/fixtures without reclassifying historical output.
- First-introduction patch on populated legacy sites creates Compatibility rows
  once with provenance; later deletion cannot rerun bootstrap and enters Recovery
  Required.
- Backfill distinguishes Person and Household Customers that both use core
  `customer_type = "Individual"`; core type alone leaves the Customer
  Unclassified and creates a review issue rather than inventing an anchor.
- Dry-run and applied backfill, interruption between batches, retry after worker
  failure/deadlock, source drift after a reviewed issue, and idempotent rerun.
- Applied backfill requires Backfill Fenced, one database-unique active run/lease,
  matching operation ownership on every batch, and stale/concurrent worker
  rejection before write. Notification/Webhook/Server Script/app-hook side-
  effect inventory blocks unknown effects and restores snapshotted automation only
  after the complete fingerprint commits.
- Good Connector bulk suppression runs for every applied batch and exactly one
  deduplicated full scan is queued only after the complete run succeeds.
- Enforcement refusal for stale fingerprint, incomplete counts, unresolved
  issue, wrong model version, or failed verification marker.
- Activation interruption before/after every fence and DDL checkpoint,
  concurrent activators, manifest mismatch, schema-observed resume after a crash,
  Recovery Required fix-forward, Active-to-Suspended fail-closed behavior, and
  preservation of activation-owned indexes through later `bench migrate`.
- Cross-control tests prohibit donation Active or Membership issuance while
  identity is Compatibility/Fenced/Suspended/Recovery Required or at another
  epoch/run/hash. Concurrent finance writers versus identity fencing follow
  `identity -> donation -> Company config -> owner -> voucher`; the fence commits
  every dependent control non-operational before identity leaves Active.
- Rename/trash/import/direct-state/missing/corrupt activation-row attempts fail
  closed; clean install seeding and evidence-aware Recovery Required
  reconstruction never erase prior activation history.
- Canonical `discard()` of activation/config controls is rejected through
  `before_discard`; generic insert/insert_many/save and REST v1/v2 create/update
  calls carrying `_action = "discard"` are rejected by the protected-DocType
  `insert`/`_save` guards before any database write.
- Protected native rename/merge tests cover Desk, `frappe.client.rename_doc`,
  REST document methods, and direct `Document.rename(validate_rename=False)`;
  caller-controlled validation bypass never reaches `frappe.rename_doc`. The
  registry includes every fixed, immutable-key, identity, Household, Membership,
  managed Subscription, Ask, Donation/event, audit, and NPO-purpose voucher
  DocType; unrelated standard
  records remain unaffected.
- Capability-manifest activation and drift tests cover relevant app
  install/uninstall/upgrade, installed order, provider/materializer version,
  required-field removal, effective hook/MRO change, stale consumer, suspension,
  and explicit reactivation. Authorized target-manifest drift under the matching
  committed fence operation remains Fenced; unexpected operational drift suspends
  and fenced drift with the wrong operation/target enters Recovery Required.
- Every post-activation install/uninstall/upgrade/hook-order operation exercises
  the explicit identity/donation
  `Active -> Fenced -> Installing Indexes -> Verifying -> Active` path and the
  Membership/Donation Configuration `Active -> Fenced -> Active` and
  `Disabled -> Fenced -> Disabled` paths using the old-release pre-deploy fence;
  stale web/worker/callback writes drain/reject before code/DDL, unfenced migrate
  aborts, and only the fully deployed/reverified capability set returns Active.
- Sanctioned installer/remover/migrate commands prove the external entrypoint shim
  rejects known and previously unknown apps before target code import, while known
  target `before_install`/
  `before_uninstall`, global `before_app_install`/`before_app_uninstall`, and
  `before_migrate` independently reject before schema/data mutation when the
  committed permit is absent or mismatched. Direct host-code execution is tested
  and documented as trusted-host scope, not falsely claimed sandboxed.
- Queue-disposition tests cover RQ queued/deferred/scheduled/failed jobs, scheduler
  events, callbacks, Deferred Work, Outbox, and Email Queue. Every relevant payload
  is drained, cancelled, migrated, or versioned for replay; unknown/stale jobs
  block activation and cannot execute after restart.
- Voucher-automation policy tests block unsafe synchronous Notification/Webhook/
  Server Script/doc-event combinations, detect post-activation config drift, and
  create one internal outbox event. Lease-expiry/send-crash tests prove
  at-least-once retry and receiver-idempotency behavior without claiming
  impossible exactly-once delivery for unsupported channels. Retention erases
  terminal payload detail but preserves the uniquely constrained event-key
  tombstone; replay after retention cannot recreate or redeliver the event.
- Runtime drift rejects the writer from the computed mismatch even before state
  persistence; rollback does not erase safety and the after-rollback fresh job
  durably records Suspended without committing the failed business mutation.
- Pre-maintenance and post-fence backups are distinct and restorable; only the
  post-fence backup may roll back DDL before Active. After Customer-model vouchers
  or external effects exist, tests reject pre-cutover restore and require fence,
  incident snapshot, provider/outbox quarantine, and reconciled fix-forward or
  point-in-time recovery without duplicate delivery.
- Epoch-provider tests cover authenticated read/CAS, absence/outage, site/hash
  mismatch, site-A credentials against site B, clone/rename namespace reset,
  controlled rename retaining UUID/incarnation, protected-history clone refusal,
  redacted successor export, clean-site initialization, signing-key rotation,
  stale process cache, and
  crashes before/after CAS. Restoring/importing a DB/files snapshot with an older or mismatched
  activation epoch fails at boot/request/worker/callback before replay and enters
  Recovery Required; the external anchor is absent from ordinary backups.
- Take a full DB/config/public/private-file backup before subject minimization,
  including PII-bearing Contact/Address/Customer/User/Communication/relationships,
  credentials and Files; then anonymize/delete, revoke credentials, and destroy its
  envelope key/blob before restore. External erasure/redaction-journal replay and
  non-web file quarantine run before service; database plaintext/linkage and old
  credentials stay absent, ciphertext remains undecryptable, stale public/private
  URLs are absent, and only the non-PII tombstone survives. Unknown-schema/
  irreconcilable replay invalidates the generation.
  Cover swapped key ID/ciphertext/AEAD context, cross-site identical blobs,
  non-exportable/no-cache DEKs, concurrent read/destroy and hold/destroy,
  same-epoch pre-hold restore, duplicate/reordered calls, provider outage/lost
  acknowledgement, and crashes at every Prepared/Destroyed/Purged/Committed
  transition. KEK/signing rotation, multi-subject hold, and backup expiration are
  mandatory.
- Provider request/log/audit/export/tombstone tests use PII-bearing filenames and
  subjects. Permanent records contain only site-scoped opaque IDs/keyed
  fingerprints; encrypted purge locators are available only to quarantine cleanup
  and disappear after affected backups expire.
- Backup/restore/start-shim tests disable direct core scheduled and live-site bench
  paths, register Preparing/Capturing/Completed/deletion/expiry attestations, and
  reject absent/stale/incoherent manifests. Concurrent protected DB/File writes,
  key rotation, hold/erasure, and Outbox delivery during every capture phase either
  share one DB/binlog/File/provider/work head or abort/attach an ordered replay
  delta; DB-to-blob reconciliation quarantines unknown/orphan content. Restore core into a non-routed staging DB/files
  root, attempt backend/static access throughout, inject erasure/hold changes, and
  allow atomic promotion/start only after purge and retained/purged fingerprint
  reconciliation. Crash before/after each restore/promote step never exposes the
  staging or prior erased public file.
- DR split-brain tests keep original web/workers/callbacks/static host live and
  partitioned before/after promotion. Promotion waits/revokes old leases, CAS-
  advances runtime generation, rotates workload credentials/routes, and stale
  requests, provider handles, final DB writes, jobs, external deliveries, restarts,
  and direct static access all fail without waiting for process restart.
- Successor-export tests apply the versioned default-deny schema to adversarial PII
  in every free-text/artifact/filename/log/identifier/hash field, abort on unknown
  fields/classes or cross-site correlation, enforce synthetic/aggregation policy,
  and attest a new-UUID/key output before release.
- Initial-versus-maintenance fence-origin tests prove only an untouched initial
  activation may return to Compatibility; maintenance can return to Active only
  after exact old-release/schema/manifest restoration and otherwise stays fenced.
- Clean uninstall requires a committed lifecycle fence, maintenance/worker drain,
  database-lock final recheck, matching before-uninstall operation ID, and durable
  site-private audit; direct or point-in-time-check uninstall fails.
- Household empty-site clean replacement and populated-site conversion with
  exact history/date/primary Person and Household Address Link reconciliation,
  removal of reverse Household Dynamic Links without Contact/Address disclosure,
  standalone Customer/role links, duplicate-role coalescence, and conflict rows.
- Membership Type collection-mode migration covers provable Invoice evidence,
  ambiguous/null review, historical settlement while blocked for new issuance,
  concurrent mode change/Ask creation, effective future cycle boundaries, and no
  mutation of issued Ask/Subscription/invoice attempts.
- Volunteer stable-name conversion preserves incoming links and aliases; email
  changes after migration neither rename nor duplicate the Volunteer.
- Legacy Donation Receipt migration preserves submitted print output and the old
  navigation link; provable Payment Entry allocations, ambiguous/manual evidence,
  refunds, corrections, and idempotent reruns produce exact classified counts.
- Legacy Payrexx/Integration Request/provider checkout adoption covers pending,
  authorized, captured, refunded, chargeback-capable, ambiguous, and externally
  divergent intents. Activation blocks until every future callback has a durable
  converted/continuation/revoked/holding disposition.
- Legacy refund/chargeback IDs and existing Credit Note/Payment Entry/Journal Entry
  tranches adopt unique Refund Source/Instruction records idempotently; ambiguous
  or still replay-capable unmapped events block activation.
- MiKi-owned legal fields remain unchanged whether Good Connector is absent or
  installed.
- Working-tree cleanliness after install, migrate, and uninstall paths.
- `before_uninstall` permits a truly clean unactivated site only with the matching
  committed lifecycle fence/drain/final recheck and vetoes non_profit removal for
  every activated/protected-history state so fence/audit DocTypes and custom
  voucher fields cannot disappear.

### 16.2 Identity and concurrency

- Person versus Generic Endpoint classification and blocked invalid transitions.
- Individual and organization Member/Donor creation, one role per operating
  identity, Supplier-only parties, and NPO Organization verified-key uniqueness.
- Person/Organization/Household/Anonymous System Customer anchors are mutually
  exclusive; Household and anonymous Customer/Donor creation are unique and
  concurrency-safe, and unrelated ERPNext Customers remain outside NPO scope.
- With the Good NPO `CH_UID` provider installed, MiKi parent/child Customers with
  the same verified UID may share one NPO Organization while retaining separate
  declaration items; without that provider, MiKi values remain claims/review
  evidence. Different UID and blank/unverified child cases remain distinct/
  reviewed. Test provider install/version/source changes, focused writes,
  collision rejection, and migration invalidation.
- Runtime organization evidence proposal, verified-key approval/revoke/transfer,
  and reviewed operating-unit links enforce their distinct permission and audit
  contracts through forms, lists, REST, and concurrent collision attempts.
- Projection Approval Active/Settlement Only/Revoked transitions, zero-dependency
  unlink, and verified-key tombstone/reactivate/transfer preserve one durable
  Active-under-new-owner key row and distinguish intentional operating Customers
  from duplicate aliases. Legal-organization consolidation is the sole projection-
  retarget path, supersedes approval history under locks, preserves accounting
  masters/vouchers, and leaves no active projection on the Archived Alias.
- Ordinary Party Links between unmarked ERPNext masters remain unchanged; one
  managed endpoint requires explicit adoption before NPO one-to-one rules apply.
- Anonymous System selector and transaction-allowlist tests reject ordinary
  orders, invoices, subscriptions, memberships/asks, payments, shares, imports,
  and direct APIs while allowing exact anonymous Donation/reversal paths only.
- Anonymous excess cannot be released or reconciled across pooled Donations;
  only same-Economic-Receipt acceptance or source refund succeeds.
- Public impersonation/enumeration tests prove exact PII knowledge cannot mutate
  an existing identity; session/one-time endpoint proof succeeds atomically and
  pending claim responses are indistinguishable across candidate counts.
- Shared/Unknown/multi-Contact email verification proves mailbox control only;
  person reuse requires an already bound session plus independent factor or staff
  review, while unique verified Personal endpoints may complete the claim.
- Verified endpoint edit/remove/copy revokes value-bound claims/tokens; concurrent
  Personal verification on two Contacts has one database-enforced winner and
  token consumption rechecks the immutable normalized snapshot.
- Canonical Contact changes with managed Dynamic Link and Address projection
  reconciliation.
- Canonical anchor retarget succeeds only on a truly unused record; Membership,
  Donation, accounting, receipt, portal, source, Household, or communication
  history freezes it and split/consolidation preserves old ownership.
- Native Desk/API `rename_doc(merge=True)` and uncontrolled non-merge rename are
  rejected for every managed identity/role/accounting master; only the audited
  operation context succeeds.
- `discard()` of managed identities, roles, and Party Links follows the same
  controlled operation guards and cannot bypass validate/cancel/trash invariants.
- Contact core deduplication preserves compatible NPO/MiKi Dynamic Link metadata
  and blocks conflicting duplicate rows before core can drop custom values.
- Concurrent financial projection, role creation, Household move, Party Link,
  archive/reactivate, consolidation, and split. Assert deterministic lock order,
  one winner, no partial writes, and retryable deadlocks.
- NPO Party Link direct trash/bulk delete/import is blocked; controlled unlink
  locks endpoints and pair approval, checks dependencies, revokes only NPO Party
  Link Approval, leaves both organization Projection Approvals intact, and records
  audit, while an unmarked core link deletes normally.
- Archived alias selector exclusion and new-activity blocking across Membership,
  Donation, Volunteer, Sales/Purchase documents, Payment Entry, imports, and
  public/Desk helpers.
- Settlement Only aliases can settle, amend, cancel, or reverse only exact
  pre-archive dependencies; unrelated new activity is rejected and final archive
  waits for open/correctable items to clear. Include Customer, Supplier, and
  legacy Member/Donor accounting parties.

### 16.3 Household and Membership

- Roleless Household people, one current financial Household per Contact, one
  current primary per Household, historical ended rows, separation, parent-owned
  Household Address Links, and no reverse Household data in generic Contact/
  Address hydration.
- Concurrent additions of different Contacts/primaries to an empty Household and
  cross-Household moves serialize on Contact then Household parent mutexes and
  cannot create two current primaries or two current Household rows for one
  Contact.
- Individual, Organization, and Household Membership scopes; covered-Member
  date bounds, administrative-member inclusion, Household/Covered Member payer
  scopes, optional billing Member, matching billing Customer, overlap prevention,
  renewal, mid-term coverage changes, and payer immutability once an ask is
  issued. Include two-transaction overlap attempts and Household Person interval
  eligibility.
- Migration of `is_household_membership = 0`, review gating for inferred true
  rows, approved Ilanga source mapping, and refusal to invent coverage.
- Family Membership joint ask in both Membership Type collection modes: Invoice
  produces one Sales Invoice against `billing_customer`, while Request produces
  no receivable until an accepted financial event, then creates one immediately
  settled Sales Invoice from linked Customer advances. Test unique cycle keys,
  rejection of foreign currency in both modes, partial/multiple/overpayments,
  fixed-amount currency precision, immutable
  Company/currency/accounts, explicit gross/net pricing and tax rows, disabled
  unintended pricing rules/discounts, rounded-total equality, retries, duplicate
  callbacks, partner/third-party remitters, residual credit/refund review, and
  ambiguous-payment review.
- Invoice/Request positive-charge builders clear live Customer payment terms after
  defaults, write one frozen 100% non-discounted schedule and legal due date, set
  `set_posting_time` plus approved date/time, and overwrite `get_payment_entry()`
  today defaults. Delayed/closed-period workers and later Customer/template edits
  cannot change submitted dates, terms, discounts, or Payment Entry references.
  Credit Notes retain approved dates but core-cleared empty terms/schedule and no
  payment-term reference.
- With ERPNext common-party accounting enabled and Customer credit limits set,
  NPO-purpose invoices never auto-create Party-Link Journal Entries; fully funded
  Request bypasses credit limit only after locked funding, while Invoice mode
  follows its explicit snapshotted enforce/bypass policy. Ordinary invoices keep
  core behavior.
- Request-mode tests cover missing separate-advance configuration, dedicated
  Payment Entry invariants, Company-currency restriction, attempted Payment
  Reconciliation candidate exclusion/consumption in manual and Process modes,
  effective Payment Reconciliation class/MRO and `super()` preservation,
  pre-limit refill when reserved rows fill the requested limit, Reversed cash in
  Reassignment Pending, and Released/Free Residual eligibility,
  persisted-candidate disposition changes between Process collection and
  mutation through the targeted `before_job` sanitizer with stale-row skip audit,
  process named lock, owner-first discovery/locks, Log Allocation rows last,
  direct Log Allocation mutation with parent marker missing/forged but NPO
  references present,
  complete-group skip looping until the exact next core group is sanitized/locked,
  injected sanitizer deadlock/exception before and after skip writes, full
  rollback, bounded fresh retry, core-job suppression, and no false completion,
  `before_update_after_submit`, cancellation before settlement, blocked
  cancellation/unreconciliation after settlement, link/submit versus settlement
  races, stable-set retry, duplicate settlement jobs, controlled Void Settlement,
  and real refund/chargeback paths.
- Process death after funding commit but before Redis enqueue leaves one Pending
  Deferred Work row; sweeper recovery, lease expiry, duplicate wake-ups, and
  worker crash create exactly one settlement invoice and permanent work-key
  tombstone.
- NPO Payment Entry tests reject mixed ordinary/NPO, multiple Asks, multiple
  Membership Subscription cycles, multiple Donations, and cross-domain references
  through builder, Desk, import, REST,
  reconciliation, and update-after-submit; one owner is discovered before lock,
  owner locks before voucher, controlled same-Donation excess references and
  disposition-bounded Free Residual/Released ordinary references pass, and non-
  NPO multi-reference payments remain normal. Any Payment Entry Deduction or
  Advance Taxes and Charges row on an NPO-owned payment fails through parent and
  direct-child paths.
- Manual/provider/bank/cash retries use unique Membership Ask Economic Receipt
  Source aliases plus the cross-channel Observation Lock, create one receipt and
  at most one active Payment Entry attempt, and cannot mark an Ask Cancelled while
  confirmed cash remains undisposed. Manual-then-bank/provider races reuse or
  enter ambiguity review; source/value/posting dates and closed-period override
  never default to callback day.
- Journal Entry and Journal Entry Account creation/import/update/cancel plus
  Payment Reconciliation/Process/Unreconcile cannot settle, write off, exchange,
  or reopen a Membership Ask or Membership Subscription charge/reversal/recovery
  invoice or reserved advance; only an exact retained-credit application passes.
- Unrelated Sales Invoices, another Ask, automatic advance allocation, imports,
  REST, and concurrent submit cannot consume Reserved/Reassignment Pending/Refund
  Pending payments; only the exact owning settlement invoice's explicit rows pass.
- Test Invoice and Request state dimensions/precedence, including no-cash partial/
  full Credit Note as Partially Reduced/Reduced, mixed reduction plus retained
  cash, collectible/retained-credit forward recovery returning to Partially
  Reduced/Issued then Partially Funded/Settled on cash, cash-gated recovery
  remaining in prior refund disposition without a false due, and proof that zero
  outstanding without cash is never Settled/Refunded;
  expired partial refund/release,
  refund cancellation, valid-advance reassignment, cycle-root successor
  uniqueness, no-copy Credit Notes, failed Settlement Pending retry, and terminal
  attempt rules.
- Concurrent/retried partial Ask refunds, provider callbacks, and refund reversal
  use unique Refund Source/Instruction keys and create at most one Credit Note and
  outgoing Payment Entry per tranche while preserving distinct later tranches.
  Tests cover applied versus standalone/split Credit Notes, advance/excess reverse
  payments submitted unreferenced then reconciled Pay-as-invoice/Receive-as-
  payment under separate-advance accounting, narrow receivable account extension,
  retained Customer credit and partial/full NPO Credit Application JE with Credit
  Note voucher type, deterministic all-owner locking, open cancellation, accepted-
  gift chargeback with one exact bank/provider-clearing Pay voucher, no-cash
  reduction, open-period cancellation, closed-period
  forward reversal and recovered Receive-to-outgoing-Pay reconciliation, immutable source/cash/recognition
  dates, rounded amount parity, and no generic debit/credit-note reconciliation JE.
- Fractional-UOM activation and refund tests cover transaction/stock UOM whole-
  number flags, conversion factors, effective `qty`/`stock_qty` precision and
  Property Setter/global drift. Partial/split Credit Notes carry the exact source
  `sales_invoice_item`, use deterministic cumulative quantity/tax/rounding
  proration, reject empty/wrong/copied row links and impossible tranches, and prove
  returned quantity never exceeds the original while every effective payable
  matches its instruction.
- Recovery Sales Invoices and Payment Entries carry only the matching refund-
  recovery purpose, reversal instruction, original Credit Note, account/date, and
  same-owner links; forged original Ask/Membership-cycle/Donation ownership or cross-purpose reuse
  fails, including closed-period and separate-advance cases.
- Recovery-disposition tests distinguish unpaid collectible reduction (forward
  charge without cash), On Receipt/cash refund (no voucher until atomic recovery
  cash), Request/excess reverse-payment recovery, Holding recapture, and
  unconsumed versus consumed Retained Credit. No path invents cash, receivable, or
  income from the wrong timing model.
- Enabling/changing Company-wide separate advances tests standard Sales Order,
  Purchase Order, Customer/Supplier Payment Entry, regional accounting, Payment
  Reconciliation, account-precedence, and reconciliation-date behavior. Open asks
  and terminal asks with pending cash block effective config drift until every
  dependent payment is settled, reassigned, refunded, released, or migrated.
- Concurrent first-Ask issuance versus Company/Customer/Customer Group/Account/
  Accounts Settings mutation locks the same Company configuration row and cannot
  commit a stale snapshot.
- Threshold-crossing value date, delayed settlement, closed-period Posting Review,
  approved first-open posting date/reason, and retry all preserve acceptance and
  revenue dates rather than using worker day. Request issuance rejects every
  reconciliation-effect policy except Oldest Of Invoice Or Advance; every Sales
  Invoice Advance/Payment Entry Reference and GL transfer uses the approved
  invoice date or rolls back.
- Issued-ask correspondence snapshots remain unchanged after recipient, language,
  Address, Household membership, or separation changes.
- Household Membership with a subscription-enabled Membership Type is rejected;
  Individual and Organization Subscription tests assert that the Subscription
  party is the Customer matching the Membership subject. Review-gated legacy
  Subscriptions continue only against their exact prior payer, including scheduler
  execution, and approved Household conversion closes them at a cycle boundary.
- Individual/Organization Membership first billing and renewals carry base
  Membership Subscription purpose, immutable Membership/Subscription/cycle owner,
  exact native `subscription`/`from_date`/`to_date` for Subscription cycles, empty
  native fields for Direct Membership cycles and all returns/recoveries, explicit
  dates/terms, and unique attempts. Existing Good NPO first-invoice adoption or
  next-period advance, process/generate/cancel/restart/force/scheduler concurrency,
  managed current/outstanding status, Payrexx settlement, retries, partial/full
  Credit Notes/refunds, future-cycle continuation/end boundary, orphan conflict,
  and MiKi exclusion are verified. Desk/API/import/update-after-submit changes to
  party/period/generation/due/cancel/plan/tax/discount/dimension/proration inputs or
  Plan Detail rows fail for open cycles; future effective policy revisions and
  concurrent shared Plan mutation produce one locked immutable cycle fingerprint.
- Membership Ask settlement with Good Connector absent uses the unique reference
  and `Payment Entry.membership_ask`; optional Good NPO/Good Connector Swiss QRR/
  EBICS automation produces the same accounting outcome when enabled.
- Swiss adapter QRR collision/candidate tests prove Invoice mode exposes only Sales
  Invoice, Request mode exposes only Membership Ask, settlement invoice has no
  duplicate QRR, and Good Connector's Company registry includes active asks.
- Household Customer creation is lock-safe and unique; joint Bank Account
  matching, Household Donor recognition, and receipt selection remain distinct.
- Household separation preserves old financial history and open-item handling,
  blocks new-period activity and repointing at the effective date, permits
  controlled settlement/correction and eligible historical receipts, and creates
  new projections only for future activity. Direct backdated creation cannot
  bypass the closure state.

### 16.4 Donation accounting

- Legacy backfill for every Donation docstatus and state, including manual paid,
  partial allocations, amendments, cancellations, receipts, and recurring rows.
- Customer-model insert after activation; fenced conversion/closure of unledgered
  legacy rows; rejection of old legacy draft submit and all new legacy direct
  allocations; amendment/continuation ownership, immutable exact party, and
  mixed-model rejection.
- Every Donation-affecting writer holds matching identity, donation-accounting,
  and Company configuration permits through commit; concurrent cutover drains Compatibility Payment Entry,
  callback, EBICS, refund, reconciliation, and receipt writers before Active.
- Donation Configuration Disabled/Fenced/Active/Suspended transitions, missing/
  corrupt/drift behavior, service-derived On Receipt versus approved pledge timing,
  rejected guest/API timing input, and concurrent Account/Item/UOM/Tax/Terms/
  precision policy mutation versus every open Intent/Receipt/event/refund/job.
- Partly funded legacy continuation tests enforce root/predecessor/sequence,
  reviewed remaining intent, one active continuation, QRR handoff, and root-level
  reporting/receipt aggregation without double count.
- Customer-model resolution for Person, Organization, Household, and Anonymous
  System Donors,
  including explicit Household recognition versus third-party payer review.
- Concurrent first Household Donations lock the Household and create/reuse one
  Household Customer and at most one explicitly selected Household Donor.
- Legacy exact-Donor direct-reference guards and Customer Invoice prohibition of
  direct Donation references; standard Employee, Customer/Supplier, and HRMS
  Payment Entry behavior remains unchanged.
- Receivable-on-submit pledge accounting, On Receipt atomic invoice/payment
  creation, event-key retry/concurrency, multiple partial receipts, native
  Payment Ledger outstanding, income recognition exactly once, Credit Note and
  chargeback/refund paths, and gateway clearing reconciliation.
- Donation invoice pricing/tax/rounding tests inject pricing rules, discounts,
  tax defaults, and rounded totals and require final gross equality before either
  voucher submits.
- Donation positive charge/recovery builders clear live Customer payment terms and
  write the frozen 100% non-discounted schedule/due date; Credit Notes finish with
  empty terms/schedule and no payment-term reference. All set
  `set_posting_time` plus approved date/time after defaults/mapping, overwrite
  `get_payment_entry()` today defaults, and reject any submit-time drift.
- With common-party accounting enabled and credit limits set, Donation purposes
  never auto-create Party-Link Journal Entries; funded On Receipt bypasses only
  after capture locks, while pledge follows its explicit enforce/bypass policy.
- Manual-to-EBICS, manual-to-Bank-Transaction, gateway-charge-to-bank-payout, and
  concurrent cross-source observations attach unique aliases to one Donation
  Economic Receipt and cannot duplicate cash or income.
- Pending/authorized/captured-review checkout plus concurrent cancellation,
  amendment transfer, provider revocation, and late confirmation either block,
  reattribute once, or refund from clearing without posting to a cancelled
  Donation.
- Payment Intent callback and Donation cancel/amend follow one Donation-before-
  Intent lock order under injected concurrency/deadlocks; provider refund states
  and independent held/reclassified/refunded totals represent full and split
  dispositions from immutable provider/Holding vouchers.
- Late/unattributed capture posts one immutable Holding Capture JE with exact
  clearing/liability/date amounts; partial/full Reclassification or Holding
  Refund clears the liability without premature income or receipt eligibility,
  including cross-period provider settlement.
- Intent confirmation immediately before/during/after accounting activation holds
  the cutover row and follows its fenced converted/continuation/holding
  disposition; no callback can reopen legacy direct allocation.
- Explicit lifecycle matrix for enforceable-pledge payment reversal, pledge
  reduction/release, On Receipt accepted refund, unaccepted excess refund,
  Donation cancellation/amendment, refund cancellation, and receipt correction.
- Concurrent duplicate/out-of-order manual, provider, EBICS, chargeback, accepted-
  gift, excess, pledge, and Holding refund retries resolve one unique Refund
  Source/Instruction per real tranche and at most one voucher per required role;
  separately keyed partial tranches and reversal instructions remain distinct.
  Each matrix case verifies Credit Note mode/outstanding, references/accounts,
  immutable economic/cash/recognition dates, closed-period overrides, and exact
  rounded tranche parity without a generic reconciliation JE.
- Posted On Receipt voucher pairs reject ordinary cancellation,
  reconcile/unreconcile, and reallocation before and after receipt issuance;
  controlled Void/Reattribute/refund paths preserve event and claim audit.
- Original pledge invoices reject direct cancellation/amendment/unreconciliation;
  controlled clerical Void/Reissue and legal Credit Note release keep Donation,
  event-attempt, and voucher ownership consistent.
- Canonical `discard()` of Donation, live Intent/Event, and NPO-purpose vouchers
  invokes the same locks/permits; forged `_action = "discard"` through generic
  insert/insert_many/save, Desk, import, document-method, or REST create/update
  paths is rejected before write and cannot bypass cancellation/reversal rules.
- Mixed referenced/unallocated On Receipt Payment Entry tests assert residual GL
  stays as standard Customer credit in receivables; later excess acceptance uses
  one unique child event and standard reconciliation, while refund recognizes no
  extra income.
- Excess Pending is excluded from Payment Reconciliation and Sales Invoice
  automatic advances until controlled accept/refund/release, including races.
- Excess refunds reference/reconcile the original receivable credit and clear it
  correctly with ERPNext separate advance accounting both enabled and disabled;
  they never mispost to the advance-liability account.
- Database-unique namespaced event keys, Donation/source lock order, concurrent
  gateway/bank callback retries, accepted-versus-unallocated-credit excess, and all-or-
  nothing Sales Invoice/Payment Entry posting.
- Donation event roots derive from immutable Donation/Economic Receipt namespace
  keys, not mutable document names; key backfill is unique/idempotent and native
  Donation/Economic Receipt/Event rename remains fenced.
- Event-root/attempt tests retain void history, permit one incremented successor,
  enforce one active attempt per pledge/receipt/excess slot, and reject concurrent
  duplicate reissue.
- Delayed callbacks retain verified source/payment dates, use reviewed
  first-open posting dates for closed periods, reject foreign-currency V1 events,
  and never default voucher posting or receipt eligibility to callback/worker day.
- Good NPO/Good Connector Swiss Donation QRR tests prove pledge exposes Sales
  Invoice only, On Receipt exposes Donation only, Intents/materialized invoices
  remain QRR-empty/non-candidates, funded/closed owners inactivate without refund
  reactivation, and legacy continuation handoff has no duplicate candidate.
- Payrexx checkout and callback settlement, manual Payment Entry, optional Swiss EBICS/QRR
  candidate matching, Bank Transaction linking, Donation receipts, statements,
  outstanding, roll-ups, Good Analytics, and Good Newsletter audiences in both
  regimes.
- Allocation-based Donation Receipts cover partial/cross-period payments,
  concurrent deterministic claim/release/reissue, typed legacy/manual sources,
  refund-before qualification, generic correction/reversal lineage, duplicate-
  allocation rejection, one immutable header recipient snapshot, selectable/
  frozen jurisdiction, and provider-owned legal decisions.
- Base qualification tests expose source allocation, retained cash, recognized,
  held/released/refunded, and prior-correction facts after partial/full Credit Note
  with and without cash refund. The provider computes the legal cap/decision; base
  rejects only duplication or an amount beyond the immutable selected source.
- Claimed allocation guards reject ordinary Payment Entry/Sales Invoice
  cancel, update, reconcile, unreconcile, or reallocation; the controlled path
  submits receipt correction before releasing/rebinding the claim.
- Journal Entry creation, update-after-submit, reconciliation, and
  unreconciliation cannot settle or alter Customer-model Donation invoice
  outstanding in V1 except exact purpose-marked Holding Reclassification or
  Released-Credit Application; forged/mismatched/unowned JEs are rejected.
- Historical Member/Donor Party Type rows remain readable after new-use
  registration stops.

### 16.5 Cross-app and security

- Full focused suites for non_profit, Good Connector, Good NPO, MiKi, MoPi,
  Barakah, Ilanga, Good MEL, Good Analytics, Good Demo, Good Event, Payrexx
  Integration, Good Newsletter, and Goodvantage App, plus compatibility smoke tests
  for Supplier/Party Link consumers.
- MiKi campaign/readiness/declaration/invoice behavior with only Organization
  Members, preserved parent/child Customers, and passive Individual Members
  excluded from declarations.
- MiKi generic Sales Invoice hooks, catalog/VAT defaults, delivery, dunning,
  export, permissions, and correspondence ignore Donation/Membership Ask/
  Membership Subscription purpose invoices and their Credit Notes while normal
  MiKi invoices remain unchanged.
- MiKi final submit uses the named writeback operation and remains atomic for
  conflict-free snapshots; stale targets, canonical conflicts, shared Contacts,
  and changed login email follow review/endpoint-proof without partial master
  mutation.
- Good NPO guest donation/signup tests preserve route/payload compatibility while
  unverified identified requests pause as opaque claims and post-proof continuation
  creates one checkout or Membership. Explicit anonymous flow remains immediate.
- Good NPO Switzerland provider tests cover selectable/frozen jurisdiction,
  individual and Household entitlement, annual/ad-hoc issue, CH_UID normalization/
  collision, and approved DE/FR/IT Original/Correction/Correction Reversal
  templates. Unsupported jurisdiction/language, missing template, provider/version
  drift, and German-law legacy-format selection fail closed.
- A finalized Swiss post-receipt refund creates one separately numbered negative
  correction referencing the original and automatically sends it to the frozen
  donor recipient in the original language; retries are idempotent, refund undo
  creates one reversing correction, and no authority notification is emitted.
  Refund/correction/claim commit atomically; injected rollback creates neither
  correction nor email. Delivery retries reuse the same correction/outbox key, and
  concurrent distinct refunds receive unique correction-series numbers.
- Good NPO/Good Connector Swiss payment-reference tests cover QR-IBAN validation,
  QRR ownership/collision/inactivation, stored legacy handoff, EBICS matching, and
  QR-bill rendering while base-only manual references remain unchanged.
- Native Membership Web Form/controller tests cover a bound Website User, no
  binding, new-person proof, shared/ambiguous email, duplicate Member email,
  Contact-less legacy row, Organization attempt, retry, stale external caller, and
  concurrent saves; no first-email selection or uncontrolled `ignore_permissions`
  insert survives activation.
- Payrexx authenticated confirmation/refund/chargeback retries preserve provider
  evidence and return applied/duplicate/review through the NPO Intent/Refund
  adapter; generic non-NPO payments retain existing behavior.
- Good Connector listing, `getdata`, `getcontact`, `putcontact`, `getaccount`,
  `putaccount`, `changeemail`, `checktoken`, and `checktokenlogin` resolve exactly
  one verified User-subject binding. Person, Organization, missing, shared,
  multi-Customer, forged-ID, migration-conflict, and provider-absent cases expose
  no hidden IDs/counts and never select the first email/Customer; changeemail waits
  for new-endpoint proof and never fans out.
- MoPi `checktoken`, task list/load/complete, upload, and certificate download use
  one enabled app-scoped User principal without requiring Contact/Customer.
  Disabled, missing/conflicting scope, shared Contact, forged app/task, and cross-
  app reuse fail; User-keyed task/certificate ownership remains unchanged and
  grants no NPO subject authority.
- Barakah principal resolution precedes its custom dispatcher and passes one exact
  enabled User plus reviewed Supplier allowlist without email expansion. Tests
  cover `checktoken`, task list/read/write, file list/download/upload, order
  retargeting, one/multiple Suppliers, Supplier-only users, generic/shared Contact,
  missing/disabled/forged binding, cancelled assignments, and cross-app isolation;
  no Customer is created.
- Good Demo automatic reset runs only on enrolled disposable sites, is all-or-
  nothing over a fully marked graph, and aborts on real/mixed payment evidence.
- Good Event identified guest registration pauses as one opaque claim, resumes the
  exact capacity/booking transaction once after endpoint proof, binds the returned
  Contact, and never mutates/selects an email match for registration or
  correspondence before proof. It also accepts Organization Company/Partnership,
  resolves Person Customer through the optional provider, and never treats
  Household/Anonymous Individual Customer as participant billing; provider-absent
  standalone behavior remains valid only outside managed identity scope.
- Good MEL provisioning resolves explicit User/canonical Contact/Partner subjects;
  migrated and new Subject Access, anonymization, disposal, and legal-hold cases
  use one stable key. Shared mailbox, alias, duplicate Contact, ambiguous legacy
  `subject_user`, retained accounting, and cross-Household fixtures cannot expand
  or erase another subject.
- Ilanga institutional rerun maps source provenance to NPO Organization/operating
  Customer/Donor without treating SHA-1 or mailbox as legal/person identity;
  cleanup archives protected history rather than deleting it.
- `ilanga_people_cleanup`, `good_event_hosted_qa_cleanup`,
  `good_event_test_data_reset`, and `miki_hosted_qa_cleanup` require enrolled
  disposable/test sites, matching graph fingerprints/locks, audits, and artifact
  permits. Mixed/unmarked/retained history aborts; accounting reverses/cancels,
  identities archive/detach, tombstones survive, and no protected child or Email
  Queue row is raw-deleted. Good Event legacy fallback is tested only without an
  active non_profit model.
- `good_connector_log_retention`, `good_connector_failed_email_cleanup`, and
  `good_demo_user_retention` classify mixed protected/unprotected artifacts, reject
  stale jobs, minimize protected evidence with tombstones, and prune only proven
  unprotected rows. Shared-email and per-User retry fixtures prove Demo purge uses
  one enrolled bound graph and cannot delete another subject's Dynamic Links,
  Contact, Communication, or User.
- Good Analytics and Good NPO metrics agree on lineage-root Recognized facts,
  while Intent is explicitly labelled; partial receipts, continuations, and
  refunds produce the specified frequency/recency/monetary values. Fixtures cover
  held cash, excess accept/release, retained credit/application, chargeback,
  partial recognition, fully refunded roots, continuation intent, and legacy
  evidence precedence against the versioned formula fingerprint.
- Good Analytics and MiKi audience providers emit canonical subject plus verified
  endpoint/version and never `Donation.email`; Good Newsletter synchronization/
  send rechecks purpose eligibility and inactivates removed/revoked/reassigned
  recipients. Shared, replaced, archived, split, and consolidated endpoint tests
  stop future delivery while preserving Subscriber/Consent Log/historical
  Recipient and delivery-event snapshots under privacy/retention rules.
- Customer-model settlement, partial/late capture, retries, continuation, refund,
  and chargeback transitions produce the versioned accepted-net-cash threshold
  qualification and at most one stable-key work item. Unpaid pledge, Held, Excess
  Pending, released credit, and void receipt do not qualify; later refund/
  recollection does not duplicate. Good NPO consumes it without `Donation.paid`
  and preserves `thank_you_sent*`; the legacy authorization facade still dispatches
  by model. Good Demo checkout/seed/refill uses Intent/settlement vouchers that
  reconcile to the same fact and acknowledgement materializers.
- Base Member/Donor forms and Good NPO navigation use the same target resolver,
  present exact legacy Member/Donor and Customer accounting targets separately,
  and never hide history once a Customer exists or repoint old ledger entries.
- NPO financial-purpose integrity tests reject forged, cleared, copied, or
  cross-linked purpose/owner/reversal combinations through Desk, mapping,
  focused writes, and direct API calls. Membership Subscription tests enforce
  original native/custom cycle fields and prove reversals/recoveries cannot copy
  Membership, Subscription, cycle/attempt, or native period ownership.
- Good Connector side-effect-free candidate selection plus post-lock Donation
  materializer derives Company and holds uncached identity, donation, and Company
  configuration permits before candidate work and through commit, then locks
  Donation before Bank Transaction, revalidates, and rolls back atomically across Sales Invoice,
  Payment Entry, and Bank Transaction. Failure performs full rollback before a
  fresh all-permit/owner/Bank-Transaction lock/recheck; a successful concurrent
  retry cannot be overwritten by stale Review/Error. No buffered callback escapes.
  Excess/ambiguous events remain unmatched.
- Unsafe synchronous Notification/Webhook/Server Script/app-hook side effects
  across every atomic-flow DocType block activation or exclude NPO purposes;
  owned effects emit after commit from NPO Accounting Outbox with at-least-once
  delivery and stable receiver idempotency key, so external calls cannot escape a
  rolled-back voucher transaction.
- Good Demo ownership/privacy queries after identity fields replace email-based
  role resolution.
- Permission matrix coverage for Desk roles, Contact/Address/User Permissions,
  migration reports, consolidation, accounting activation, guest ambiguity,
  redaction, raw issue/activation row denial, and direct API/REST access.
- Generic Personal Data Download/Deletion guest forms, processors, scheduled
  work, and `user_data_fields` cannot select NPO subjects by shared email. Verified
  stable-subject requests produce one allowlisted private export or retention-
  aware audited anonymization without touching another Contact/Household person.
- Protected-RPC registry tests call ERPNext party/contact/address/bank helpers with
  caller-supplied ignore flags, Desk open counts/link titles/search, parent Data
  Export, report download, and upstream-signature drift; no protected value,
  existence, count, title, or child row escapes.
- Dashboard Chart tests cover caller-supplied definitions, unauthorized creation,
  Heatmap filters/`no_cache`, privileged-cache warming then partial-user access,
  permission revocation, and filter/date/user/formula cache separation. Protected
  aggregates use authorized rows and leak no count/date/sum.
- Existing/new protected Files are private with source-derived permissions; public
  URL migration removes old access, File-ID attachment copy checks source read,
  retarget/share/download/delete enforce both old/new targets, and recipient
  artifacts use only short-lived purpose-bound delivery. Same-hash protected/
  unprotected uploads, privacy changes, optimization, raw relink helpers, and
  concurrent delete clone/isolate blob groups and never share or overwrite one URL.
- With Goodvantage installed in each effective app/MRO order, receipt-source plus
  NPO-protected, NPO-only, receipt-only, and unrelated Files exercise create/list/
  query/read/download/copy/retarget/delete/share and DocShare validation. Core,
  receipt, and NPO predicates intersect; neither mixin/query hook can override or
  OR-bypass the other, and unrelated Files remain unchanged.
- Data Import tests stage successful/failing protected PII and accounting rows.
  Data Import parent/File/preview/warning/job/Log inherit target protection, public
  Google Sheets is rejected, direct `DataImportLog.db_insert` is minimized before
  SQL, and a lone System Manager cannot list/download/preview/read logs while the
  matching raw authority can.
- Communication/Email Queue/Comment/Notification/mention tests cover automatic
  Dynamic-Link fan-out, multiple permission domains, attachment URLs, recipient/
  CC/BCC content, timeline/list/report/export/REST, and unauthorized mentions.
  Conflicting artifacts split/unlink under audit and never expose a hidden target.
- Document Follow creation/RPC/scheduled email, parent `_comments`, optional-column
  list reads, assignments, ToDo descriptions, auto-share, and auto-follow expose
  no protected content; unauthorized mention/follow/assignment is rejected and
  existing rows are scrubbed/revoked.
- Error Log normal/deferred insert, RQ Job list/load/count/failure registry, and
  Scheduled Job Log capture only opaque protected incident IDs. Raw arguments and
  tracebacks live only in domain-restricted Protected Diagnostic and follow tested
  retention/minimization. Sentry, request JSON/form, worker stdout/file logs, and
  Redis failure text are intercepted before emission; injected protected errors
  leak only the generic incident ID.
- Submission Queue background submit/workflow tests inspect Redis payloads for
  opaque keys only; list/status/error/unlock/retry recheck the target, injected PII
  exceptions become incident IDs, permission/model drift before execution fails,
  and retention leaves replay tombstones without document/traceback disclosure.
- Tag/title RPCs, Access/View/API/Route logs, Integration Request headers/payload,
  `_seen`, `_liked_by`, and email-read pixels inherit/minimize source protection
  and expose no hidden title, report HTML, credential, recipient, or identifier.
- For every serialization-sensitive parent, a user without raw-field authority is
  denied generic set_value/save/insert/insert_many/submit/cancel, REST v1 create/
  update, REST v2 mutation/document RPC, and Desk mutation even when a narrower
  business command is allowed; the purpose-specific command returns only a newly
  constructed redacted result. Raw-authorized users and unrelated standard rows
  retain normal behavior.
- Every protected mutator is exercised through normal RPC, REST v1 `run_method`,
  REST v2 document method and `run_doc_method` using POST and authenticated GET/
  HEAD/OPTIONS. Dispatcher and method checks reject read verbs before any DB,
  File, lock, Redis, queue, email, or external effect.
- Injected late controller/app/Server Script hooks cannot change protected scalar
  anchors, markers, keys, purpose/owner links, or state after entry validation;
  final `db_insert`/`db_update` fingerprints reject before SQL.
- Protected changes create restricted NPO Protected Change Audit rather than raw
  core Version diffs. Pre-existing Version rows are migrated/minimized, and form
  docinfo, Version list/report/export/REST, and timeline tests expose no restricted
  field or child value to a partial reader.
- Protected Deleted Document snapshots are classified and minimized to non-PII
  tombstones after durable audit. Direct/bulk restore, `flags.from_restore`,
  partial-reader access, and stale pre-activation snapshot tests cannot recreate
  or disclose protected state; tests invoke core's direct `db_insert()` path and
  prove the mixin minimizes before SQL. The named recovery path reruns current
  invariants.
- Transaction Deletion Record validation, submit, queued worker, direct
  `execute_task`, parent batch, child batch, tampered-row, and stale-worker tests
  cannot delete registry or NPO-managed/purpose data on an activated/protected-
  history site. Activation refuses queued/running jobs and verifies the effective
  ERPNext extension/MRO and worker guard hash.
- Repost Accounting/Payment Ledger validation, range expansion, direct worker,
  stale fingerprint, and failure tests require one fenced Ledger Repost Run, lock
  all owners before vouchers, and reconcile GL/PLE/advance/claim/fact fingerprints
  before reactivation.
- Generic classic/raw/WeasyPrint, print permission, website permission,
  `ignore_print_permissions`, email attachment/view-link, and existing/new
  Document Share Key paths require raw authority or fail. Recipient-facing
  correspondence renders a redacted immutable snapshot and exposes no generic
  share key.
- Prepared/Auto Email Reports and report Files bind requesting user, filters,
  formula/source and row-authorization fingerprints; cross-user/stale download or
  scheduled delivery fails, while protected Query/Script reports cannot bypass row
  providers.
- A malicious System Manager cannot self-assign or seize/prepare another protected-
  authority account through User/Has Role, Role Profile, import, Desk, REST/RPC,
  password reset, enabled/user-type/login/2FA/session mutation, `generate_keys`, or
  `get_password`, in credential-then-role or role-then-credential order. They also
  cannot alter Role/DocPerm/security artifacts, use System Console/full backup, or
  enable database-authored Server Scripts/custom Query/Script Reports.
  Administrator/host actions follow the explicit trusted boundary and capability
  audit.
- Impersonation tests POST the real endpoint as System Manager with core/custom
  impersonate grants against Administrator and dual-role authority, then exercise
  pre-existing/forged `impersonated_by` sessions. Activation revokes grants and
  sessions; only literal Administrator may start impersonation, and every
  impersonated session is barred from protected reads/actions until switch-back.
- The real `update_installed_apps_order` RPC rejects non-Administrator and absent,
  stale, or mismatched target-manifest permits. Concurrent stale workers prove no
  protected write runs under mixed hook order; all controls remain Fenced until
  every process reloads/verifies the new MRO/hash.
- Audit Trail direct document RPC checks the selected and every amended document
  under the identity/accounting conjunction; linked-document and cancel-all APIs
  return no inaccessible IDs/counts and no partial unsafe dependency tree.
- Mixed target permissions deny raw Household/Household-Membership parent/list/
  REST access and the summary API exposes only authorized projections without
  hidden IDs or counts.
- Generic Contact and Address form/REST hydration exposes no reverse Household
  link or association; only the authorized Household loader returns parent-owned
  Household Person and Household Address Link projections.
- Direct generic list, report, export, named-read, REST v1, and REST v2 access to
  sensitive identity child DocTypes is denied even when the caller can read the
  parent DocType class; permitted parent hydration and redacted summary APIs are
  tested separately.
- Direct insert, update, bulk update, retarget, canonical/forged discard, trash,
  and delete of every
  parent-only identity/accounting child registry entry fails through Desk,
  `frappe.client`, REST v1/v2, and document RPC. The same mutations succeed only
  inside the locked parent service and still execute parent invariants.
- Parent-mediated `frappe.client.insert_doc/delete_doc`, full parent REST/Desk
  save, new-parent child insert, and `update_children` SQL deletion all hit the
  persisted/requested child-diff guard before write; forged additions, removals,
  and retargets cannot bypass child locks or invariants. Injected before_insert/
  validate/before_save hooks that mutate a protected child fail the final semantic
  fingerprint at parent `db_insert`/`update_children` before child SQL.
- Permitted protected physical deletion pre-cleans every artifact and persists a
  cleanup permit; the after-commit `delete_dynamic_links` job proves a no-op.
  Injected residual/follow/comment/share rows or a missing permit fail without raw
  unlink/delete.
- DocShare create/update and pre-existing-share activation tests prove shares
  cannot OR-bypass Household/Household-Membership raw PII restrictions. Scope is
  immutable after insert; DocShare create/update/retarget and fenced legacy
  conversion use the same target-parent mutex, and conversion locks/removes shares before
  switching to Household so share creation cannot race the invariant. Forged
  DocShare `_action = "discard"` retargets are rejected before validation can be
  skipped; canonical DocShare discard is rejected, while concurrent native
  unsharing takes no parent lock, remains idempotent, and does not deadlock
  conversion.
- Discard/trash-policy tests cover every protected-lifecycle registry entry,
  especially migration evidence, verified endpoint/key, immutable audit/event,
  Identity Claim, and Outbox rows, plus authorized payload minimization and
  controlled parent-operation exceptions; activation fails when an entry lacks
  its declared effective guards.
- Retention/legal-hold tests cryptographically erase expired revoked endpoint,
  Protected Change Audit, privacy, and diagnostic payloads while preserving
  non-PII immutable tombstones; active evidence and held records cannot erase.
- Explicit role-conjunction tests prove DocPerm OR behavior cannot bypass
  System-Manager-plus-Accounts-Manager guards.
- Customer/Supplier Partnership remains available with MiKi installed, while
  MiKi imports and declarations continue using their precise legal-form rules.
- Compatibility telemetry proves old helper signatures and payloads continue to
  work before any removal clock starts.

## 17. Explicit Non-Goals

- Do not modify ERPNext or Frappe core DocTypes directly.
- Do not implement jurisdiction-specific receipt law, legal wording, numbering,
  templates, country/currency/language defaults, organization-identifier
  normalization, QRR, or QR-bill presentation in `non_profit`. It owns generic
  facts, integrity, selectable jurisdiction snapshots, and provider interfaces;
  Switzerland V1 belongs to `good_npo`, while Good Connector owns Swiss payment-
  reference transport mechanics.
- Do not let a payment/transport integration decide receipt entitlement,
  recipient, legal document kind, or organization identity verification.
- Do not collapse Customer and Supplier into one custom accounting party.
- Do not use NPO Organization as a ledger party; it groups legal identity while
  Customer and Supplier remain the standard accounting masters.
- Do not enforce verified legal identity uniquely on each operating Customer or
  infer it from MiKi parent hierarchy alone; use NPO Organization verified keys.
- Do not create one Customer per role, accounting Company, campaign, or app.
- Do not use email as the permanent identity key.
- Do not rewrite submitted ledger history as part of identity cleanup.
- Do not make Customer Payment Entries reference Donation directly or maintain a
  parallel custom payment ledger; new donation accounting uses standard Sales
  Invoice, Payment Entry, Payment Ledger, and Credit Note behavior.
- Do not settle Customer-model Donation invoices through ordinary/untyped Journal
  Entry in V1. The only exceptions are exact service-owned Donation Holding
  Reclassification and Released-Credit Application paths with typed source,
  two-row account/reference matrix, idempotency, and mutation guards.
- Do not make two people share one Person-subject Customer. Joint financial
  activity uses a dedicated Household-subject Customer linked to Household.
- Do not register Household as a custom ERPNext Party Type or add Household to
  core `Customer.customer_type`; standard accounting continues through Customer.
- Do not represent an organization as a person Contact; organization Contacts
  are representatives or communication endpoints.
- Do not introduce a generic Constituent DocType unless Household financial
  identity or another approved requirement cannot be represented safely with
  Customer, Supplier, Contact, and Household.
