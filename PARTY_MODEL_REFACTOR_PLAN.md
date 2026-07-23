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

- One natural person has at most one active Individual Customer for a selected
  canonical Person Contact. For organizations with verified legal identity
  evidence, the system prevents more than one active canonical Customer for
  that evidence. Organizations without verified evidence remain subject to
  duplicate review rather than an unprovable uniqueness claim.
- Member, Donor, and Volunteer are roles, not competing identity records.
- A person who is both a Member and Donor reuses the same canonical Contact and,
  once financially relevant, the same Individual Customer.
- A Person Contact is the canonical person identity; Contacts also represent
  non-person communication endpoints when explicitly classified that way.
- Customer is an individual's optional receivable/accounting projection.
- Customer is the organization anchor for established Member, Donor, or other
  receivable-side NPO roles, even before the first financial transaction.
- Supplier remains the payable/accounting representation.
- A payable-only organization may remain Supplier-only; it must not receive a
  Customer solely to satisfy this identity proposal.
- Household groups people rather than Member or Donor role records.
- Existing submitted accounting history remains valid throughout migration.

## Proposed Architecture Direction

The following points are the recommended direction, not activated requirements:

1. A Contact explicitly classified as `Person` is the canonical identity for a
   natural person. A generic mailbox, department, or other communication
   endpoint remains a Contact but cannot anchor person identity.
2. An Individual Customer is created only when that person becomes financially
   relevant. Creating a Member, prospective Donor, or Volunteer alone does not
   require one.
3. An organization is represented by a Company or Partnership Customer as soon
   as it becomes an established Member, Donor, or other receivable-side NPO
   party. A Customer may therefore exist before any invoice, Donation, or
   payment. A payable-only organization may remain Supplier-only.
4. Contacts linked to an organization Customer are its representatives or
   communication endpoints; they are not the organization identity.
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

## 2. Vocabulary

| Concept | Meaning | Proposed system record |
|---|---|---|
| Person | A natural person | Contact with identity kind `Person` |
| Generic communication endpoint | Shared mailbox, department, office line, or unnamed endpoint | Contact with identity kind `Generic Endpoint`; never a person identity anchor |
| Organization | Company, association, foundation, NGO, public body, or partnership | Customer for established receivable/NPO roles; Supplier for payable roles; both when needed |
| Receivable party | A person or organization from whom money is received or invoiced | Customer |
| Payable party | A person or organization that is paid | Supplier |
| NPO role | A relationship held by a person or organization | Member, Donor, or Volunteer |
| Role activity | A dated or financial event under a role | Membership or Donation |
| Household | A dated social or mailing group of people | Household with Contact-based member rows |
| Communication point | Email, telephone, or named representative | Contact |
| Location | Personal, office, postal, shipping, or billing address | Address |

ERPNext's coarse legal-nature classifications remain:

- Customer: Individual, Company, Partnership
- Supplier: Individual, Company, Partnership

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

Customer [Company | Partnership]
  +--> Member role (optional)
  +--> Donor role (optional)
  +--> Contacts as representatives
  +--> Addresses

SUPPLIER-ONLY ORGANIZATION

Supplier [Company | Partnership]
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
  +--> current Contact Dynamic Links as derived Desk projections
  +--> Shared Address through Dynamic Link
  +--> Optional billing Customer, only if joint billing is an approved rule
```

### 5.1 Identity links versus communication links

The target retains direct canonical fields and Frappe Dynamic Links, but they
have different meanings:

- Direct fields such as `Member.contact`, `Donor.contact`,
  `Volunteer.contact`, and `Customer.gc_individual_contact` are the identity
  source of truth.
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
- A shared Household Address links to Household.
- Member, Donor, and Volunteer do not own new Address identity. Legacy
  role-linked Addresses are relinked to the resolved Contact, Customer, or
  Household during remediation before role-only links are retired.
- Creating an Individual Customer or Supplier projection adds the relevant
  Contact and Address Dynamic Links without moving or deleting person-owned
  records.

## 6. Proposed Identity Rules

### IR-01: One Individual Customer per canonical Contact

A Person Contact may be linked to many Company or Partnership Customers as a
representative, employee, billing contact, or other contact person. It may be the
identity Contact for at most one Individual Customer.

Do not use email as the unique identity key. Emails can change or be shared.
Use an explicit stable Contact link, with normalized email/name/address only as
matching and duplicate-review evidence.

Implementation candidate:

- Add a nullable unique Link field on Customer for the NPO individual identity
  Contact (`gc_individual_contact`), owned by Good Connector.
- Populate it only when `customer_type == "Individual"`.
- Require the linked Contact to have `gc_identity_kind = "Person"` once strict
  enforcement is active.
- Keep `customer_primary_contact` as the operational primary Contact; do not use
  that mutable preference as the sole identity constraint.
- Multiple null values remain valid for organization Customers.
- Archived aliases clear `gc_individual_contact` and point to their active
  canonical Customer through `gc_canonical_customer`; they do not consume the
  unique identity key.

Recommended ownership is split by domain:

- `good_connector` owns canonical Contact fields on Customer/Supplier, shared
  financial-party matching, Contact identity kind, legal identity fields,
  duplicate review, alias fields, and strict Party Link validation.
- `non_profit` owns Member, Donor, Volunteer, Household, and their role
  invariants.

If required `non_profit` creation and validation paths call Good Connector's
canonical identity services, `good_connector` must become an explicit
`required_apps` dependency of `non_profit`; required invariants must not hide
behind optional imports.

This rule proves one Customer per selected canonical Contact. It does not by
itself prove one Contact per real person. Duplicate or source-preserved Contacts
remain an identity-review concern and must be consolidated or explicitly marked
as aliases before the stronger real-person claim can be made.

### IR-02: Member identity depends on Member type

Member gains an explicit subject type and identity anchor:

| Member type | Required identity | Customer meaning | Uniqueness |
|---|---|---|---|
| Individual | Contact | Optional financial projection | At most one Member per canonical Contact |
| Organization | Company or Partnership Customer | Organization identity and financial projection | At most one Member per organization Customer |

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
Declaration must have `subject_type = "Organization"` and exactly one Company or
Partnership Customer. MiKi keeps its canonical chain:

```text
Membership -> Member -> Customer -> MiKi Declaration
```

Generic Contact-only Individual Members, including MiKi's passive individual
membership type, remain valid in `non_profit`, but are not eligible for MiKi
declaration campaigns. Current MiKi declaration validation rejects a Member
without Customer, campaign selection joins through `Member.customer`, and
migration treats multiple Members for one Customer as a conflict. The refactor
must additionally enforce Organization subject type and Company/Partnership
Customer type at both campaign-selection and declaration-validation boundaries.

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
| Organization | Company or Partnership Customer | Organization identity and financial projection | At most one Donor per organization Customer |

The direct `Donor.contact` field is authoritative for Individual Donors.
Contact-to-Donor Dynamic Links remain managed projections and may not select a
different person.

An Individual Donor may exist before making a Donation without Customer. The
first financial event must resolve or create one canonical Individual Customer
and bind it to the Donor before posting.

Anonymous donations require a separately approved system identity rule and are
excluded from the normal Contact uniqueness invariant.

### IR-04: Financial projections are created at explicit triggers

Creating an Individual Member, prospective Donor, or Volunteer does not create a
Customer. The initial proposed triggers are:

- First Donation
- Paid Membership or Subscription
- Membership invoice
- Sales Invoice or another receivable transaction

Every trigger must reuse the existing Individual Customer for the canonical
Contact and must send ambiguous identity matches to review.

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
validation must enforce at most one paired Customer per Supplier and one paired
Supplier per Customer. Individual pairs must resolve to the same canonical
Contact. Organization pairs require compatible party types and matching legal
identity evidence such as UID, or explicit staff approval when no identifier is
available.

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

Good Connector adds `Contact.gc_identity_kind` with values:

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

### IR-09: Direct fields and Dynamic Links cannot disagree

For Individual Member, Donor, Volunteer, Customer, and Supplier records:

- The direct canonical Contact field is authoritative.
- Good Connector adds `Dynamic Link.gc_identity_projection` and
  `gc_identity_owner_field` so a generated projection can be distinguished from
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

For Household, current Household Person rows are authoritative. Current
Contact-to-Household Dynamic Links are a rebuilt projection used by
`load_address_and_contact`; ended historical people are not projected as current
contacts. Household Address Dynamic Links remain normal editable shared-address
relationships.

### IR-10: Organization canonicality is evidence-bounded

The model does not claim that arbitrary organization names prove legal
identity. `Customer.business_uid` is the preserved Swiss UID value. After
validation, Good Connector writes its normalized value to nullable unique
`Customer.gc_active_organization_key` only on the active canonical Customer.
Archived aliases retain `business_uid` for history but clear the active key.
Strict activation therefore enforces at most one active Company/Partnership
Customer per verified UID without erasing alias evidence. Supplier uses the
equivalent `gc_active_organization_key` when available, and Customer/Supplier
pairing must agree on normalized evidence.

Organizations without verified UID or equivalent approved legal identifier may
still exist, but name/address similarity produces duplicate-review candidates,
not automatic merge or a false uniqueness guarantee. Staff may approve one
canonical record and archive proven aliases. The top-level objective is limited
accordingly.

### IR-11: Archived aliases have explicit lifecycle fields

Good Connector owns these shared identity and accounting-master fields:

- `Contact.gc_identity_status`: `Active` or `Archived Alias`.
- `Contact.gc_canonical_contact`: Link to Contact, required only for an archived
  Contact alias. An archived Contact cannot anchor an active role or financial
  projection.
- `Customer.gc_identity_status`: `Active` or `Archived Alias`.
- `Customer.gc_canonical_customer`: Link to Customer, required only for an
  archived Customer alias and forbidden on an active Customer.
- `Supplier.gc_identity_status`: `Active` or `Archived Alias`.
- `Supplier.gc_canonical_supplier`: Link to Supplier under the same rule.

non_profit owns equivalent role fields:

- `Member.identity_status` and `Member.canonical_member`.
- `Donor.identity_status` and `Donor.canonical_donor`.
- `Volunteer.identity_status` and `Volunteer.canonical_volunteer`.

Archiving is a controlled operation, not an ordinary field edit. It requires a
dependency preview, locks alias then canonical records in deterministic
doctype/name order, sets ERPNext `disabled` where available, clears unique
canonical Contact/organization keys from the alias, records the canonical link
and reason, and writes an immutable audit result. Archiving a Contact first
retargets or resolves every active canonical role/accounting field and managed
projection; unresolved portal User, source-ID, or communication ownership is a
blocking conflict. Archived aliases retain the minimum historical display and
accounting links required by submitted records, but validation blocks new
Memberships, Donations, engagements, invoices, Payment Entries, or other
activity. Normal Link queries exclude them. Reactivate is allowed only after the
same uniqueness and dependency checks pass.

### IR-12: Uniqueness is concurrency-safe

- Use database unique indexes for unconditional keys after aliases have cleared
  those keys.
- Where MariaDB cannot express a conditional active-only unique constraint,
  lock the canonical Contact or normalized verified organization identity row
  before lookup/create and recheck under the lock.
- Financial-projection creation locks the Person Contact before querying or
  inserting Customer/Supplier.
- Role creation locks the canonical Contact or organization Customer before
  querying or inserting Member/Donor/Volunteer.
- Household mutation locks Person Contacts in sorted name order before locking
  Household Person rows, preserving the current party-before-child lock order.
- Party Link validation locks both accounting parties in sorted
  `(doctype, name)` order before checking either direction.
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
  dates and primary status, create Household Person rows, rebuild current
  Contact Dynamic Link projections, preserve Household Address links, and
  compare source/target counts before retiring the old rows.
- A role that has no unambiguous Person Contact is a blocking migration issue;
  the migration must not choose by first email or first Dynamic Link.
- Development data may be reset only through an explicit operator command after
  export and only when the operator chooses reset instead of conversion. Install
  or migrate never resets it automatically.
- The Ilanga importer and its requirements/tests must move to Contact-based rows
  in the same coordinated release. Existing imported data is converted or
  deliberately reimported from its protected source; it is not silently lost.

### 7.3 Household invariants

- Only a Contact classified as `Person` may appear in Household Person.
- A Contact may have at most one current Household.
- A Household may have at most one current primary person.
- Historical rows are ended with `to_date`, not deleted.
- Organization Customers and Suppliers cannot be Household people.
- Shared Address remains a standard Address linked to Household.
- Current Contact-to-Household Dynamic Links are derived projections rebuilt
  from Household Person; users do not edit those links independently.
- Member, Donor, and Volunteer forms may display a derived Household resolved
  through their canonical Customer/Contact, but must not own writable household
  state.

Household validation locks all affected Person Contacts in sorted order before
it locks current Household Person rows. Sync reconciles both saved and persisted
prior rows so ending, removing, or retargeting a row cannot leave stale current
Dynamic Link projections. Concurrency tests must retain the current
party-before-child lock-order guarantee.

A household going apart is handled by ending dated Household Person rows and
creating or updating the resulting Households. It never splits or duplicates the
people's Contact, Member, Donor, Volunteer, Customer, or Supplier identities.

### 7.4 Family Membership and joint asks

Family Membership is a proposed supported Household use case. If accepted, it
must be explicit rather than inferred merely because an Individual Member
belongs to a Household.

Membership gains a scope:

- Individual
- Organization
- Household

Proposed Membership fields are:

| Field | Rule |
|---|---|
| scope | Select: Individual, Organization, Household; required after migration activation |
| member | Existing required primary/administrative Member link |
| household | Required only for Household scope |
| billing_customer | Optional until a receivable is created; then required and immutable for that receivable |
| covered_members | Table of `Membership Covered Member`; allowed only for Household scope |

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
- `billing_customer` identifies one designated Individual Customer for
  accounting when an invoice or receivable is created.
- The joint ask is addressed to Household using its joint salutation and shared
  correspondence Address.
- The ledger party remains `billing_customer`; the Household is the membership
  scope and addressee, not an ERPNext accounting party.

The administrative `member` must be one of the covered Members and must belong
to the selected Household on the Membership start date. Every covered Member
must be Individual and anchored to the same Person Contact snapshot. Duplicate
or overlapping coverage rows for one Member are rejected. Two active Household
Memberships of the same Membership Type cannot cover the same Member over an
overlapping period. Coverage changes are made by ending and adding dated rows,
not by rewriting prior periods.

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
- The old flag is removed only after every deployed row has an explicit scope
  and all Household coverage issues are resolved.

One transfer from either partner may settle the joint ask, but ERPNext allocation
still uses the designated billing Customer. If the payer differs from that
Customer, retain the remitter evidence without creating a second invoice or
changing the historical membership identity.

The remaining accounting decision is whether the joint ask creates a legally
collectible Sales Invoice immediately or remains a non-ledger request until
payment/acceptance. It must not be represented as an unpaid Sales Invoice when no
legal receivable exists.

### 7.5 Household donations and receipts

If a gift and tax receipt always belong to one legal person or organization,
keep the transaction on that person's Customer/Donor and aggregate Household
giving only in reports.

If a Household must itself be the legal donor or receipt addressee, the proposed
Customer-centric model is insufficient because ERPNext has no Household
Customer Type. That requirement is a decision gate for introducing a generic
Constituent layer or an explicit Household financial-party design.

## 8. Donation Accounting Decision

The proposed end state is for Customer to be the consistent receivable party for
membership and donation money, while Donor remains the fundraising role and
Donation remains the gift/reference document. This final choice is still listed
as a decision gate because production accounting history must be confirmed.

Changing only `Payment Entry.party_type` from Donor to Customer does not work.
ERPNext applies stricter reference validation to Customer, does not currently
list Donation as a valid Customer reference, and expects the reference document
to expose a matching `customer` field.

Customer-based Donation posting therefore requires:

1. Add `Donation.customer` as a read-only snapshot of the financial party.
2. Resolve or create that Customer from the Donor's canonical Contact before the
   first financial posting.
3. Add `Donation.accounting_party_type` (`Donor` or `Customer`) and Dynamic Link
   `Donation.accounting_party`. Both are assigned together and become immutable
   no later than submit. Any Payment Entry reference also freezes them.
4. Use a narrowly scoped Frappe v16 `extend_doctype_class` mixin that overrides
   only `get_valid_reference_doctypes`, calls `super()`, and adds `Donation` for
   Customer parties. This is an explicit exception to the current
   doc-events-only rule because ERPNext rejects the reference inside controller
   validation before a `validate` doc-event can admit it. Do not override the
   whole Payment Entry class or its validation chain, and do not restore an
   install-order-sensitive `override_doctype_class`.
5. Validate both `Payment Entry.party_type` and `Payment Entry.party` against
   immutable `Donation.accounting_party_type` and
   `Donation.accounting_party` for every regime. The legacy Donor regime must
   explicitly verify `Payment Entry.party == Donation.donor`; ERPNext's generic
   path does not provide that association check for Donor.
6. Resolve the receivable account from the immutable accounting party for the
   selected regime.
7. Keep the existing hook-based company, locking, allocation-total, paid-state,
   reconciliation, and QRR checks.
8. Reject any attempt to allocate one Donation through both Donor and Customer.
9. Update receipt, reporting, analytics, bank reconciliation, and outstanding
   logic to use the immutable Donation posting regime rather than the Donor's
   current mutable Customer link.

The mixin is not allowed to absorb existing Donation behavior. Company checks,
party/account equality, row locking, cumulative allocation, paid state,
reconciliation, and QRR behavior remain in the current module-level
`doc_events` handlers. Tests must inspect the effective class with HRMS
installed, prove that the mixin precedes `EmployeePaymentEntry` in the MRO,
exercise `super()`, and verify that Employee, Supplier, Customer invoice, and
legacy Donor references remain unchanged.

### 8.1 Donation regime backfill and cutover

Customer accounting is activated per site, never merely by installing code.
`Non Profit Settings` gains a persisted accounting model version, activation
timestamp, and enable flag. Activation locks the Settings row so Donation
creation and activation cannot race.

Before activation:

- Every existing Donation in every docstatus, including drafts, submitted,
  partly allocated, manually paid, cancelled, amended, receipt-linked, and
  recurring-generated rows, is backfilled to
  `accounting_party_type = "Donor"` and `accounting_party = donor`.
- `Donation.customer` may be populated for identity/navigation, but it does not
  change the immutable legacy accounting party.
- Any Donation with missing Donor, mixed party references, or contradictory
  accounting history is a blocking remediation issue.
- The audit includes Payment Entry, Journal Entry, GL Entry, Payment Ledger
  Entry, Party Account, opening balances, Bank Transaction links,
  reconciliation/unreconciliation records, Donation Receipt, manual paid state,
  and any other Dynamic Link or reference to Member/Donor Party Type.
- Source and backfilled counts plus a hash/fingerprint are persisted in the
  migration run. The operation is resumable and idempotent.

Activation then establishes this deterministic boundary:

- All pre-existing Donations remain legacy Donor regime permanently, including
  old drafts first submitted after activation.
- A Donation inserted after activation resolves/creates Customer while holding
  the canonical Person Contact or organization Customer lock and snapshots the
  Customer regime on insert. It cannot be saved as a Customer-regime Donation
  with unresolved or ambiguous identity.
- Amendments inherit the amended Donation's regime and exact accounting party so
  accounting corrections cannot cross regimes.
- New installments from a Recurring Donation use the regime active when each
  Donation is inserted; the generated Donation stores the immutable result.
- Cancellation never clears regime fields. Reopening or editing a draft cannot
  change a regime after any accounting reference exists.
- Payrexx, EBICS/QRR, manual Payment Entry, reconciliation, reporting, receipt,
  analytics, and outstanding paths dispatch from the stored regime, never from
  creation date or the Donor's current Customer.

The legacy regime can be omitted on a site only when the complete audit proves
that no persisted Donation or accounting history requires it. Absence of Donor
Payment Entries alone is insufficient. A development site may choose an
explicit destructive reset only after export; migrate never infers that choice.

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

Household separation changes dated Household Person relationships only. End the
old rows, create or update the resulting Households, and assign future shared
Addresses and communication preferences. Person and financial identities remain
unchanged.

### 9.2 Duplicate consolidation

Use when two records represent the same real person or organization:

1. Select the canonical Contact or organization Customer.
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
party with submitted history normally remains as an archived alias linked to the
canonical party; it is blocked for new transactions but retained for historical
documents. Do not rewrite submitted GL or Payment Ledger party identity merely
to make the master list look deduplicated.

Archived aliases require an explicit identity status and canonical-record link.
Only the active canonical record carries the unique canonical Contact or active
role constraint. An archived Customer, Supplier, Member, Donor, or Volunteer
alias retains the minimum links needed to explain historical documents, cannot
receive new transactions or role activity, and is excluded from active
uniqueness checks and normal selectors. The concrete fields and lifecycle are
defined in IR-11; this section does not imply an unmodeled status flag.

### 9.3 Identity split

Use when one record incorrectly represents two real people or organizations:

1. Create the missing Contact, role, Customer, or Supplier records.
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
- Contacts linked to multiple Individual Customers.
- Individual Customers without a stable identity Contact.
- Individual Member or Donor roles without an unambiguous Contact.
- Organization Member or Donor roles without an organization Customer.
- Multiple Individual Members or Donors for one canonical Contact.
- Multiple Organization Members or Donors for one Customer.
- Member and Donor records that appear to represent the same person but use
  different Contacts or Individual Customers.
- Volunteers without Contact or with duplicated email identity.
- Every Contact and Address Dynamic Link to Member, Donor, Volunteer, Household,
  Customer, and Supplier, including links that disagree with proposed direct
  canonical fields and role-only Addresses needing relocation.
- Every Payment Entry, Journal Entry, GL Entry, Payment Ledger Entry, and
  opening-balance row using Member or Donor Party Type, including open or partly
  paid Donations, on every deployed site.
- Customer/Supplier pairs that likely represent the same entity but lack Party
  Link.
- Existing one-to-many, reverse, or type-incompatible Party Links.
- Individual Suppliers without a canonical Contact or with a Contact already
  assigned to another active Individual Supplier.
- MiKi Members that do not resolve to exactly one organization Customer, and
  Customers linked to multiple MiKi-eligible Members.
- MiKi parent/child Customer hierarchies, child-specific Members, and existing
  declaration-item relationships that consolidation must preserve.
- Household, Household Person/Member, `Customer.household`, and
  Contact-to-Household Dynamic Link counts on every deployed site. The clean
  replacement may proceed only when this preflight proves no production use.
- Every inferred household Membership, its possible Household, current people,
  payer evidence, and whether an approved source can prove covered Members.
- Existing disabled Customers/Suppliers and any informal Member/Donor aliases
  that require explicit status and canonical links.
- Verified organization UIDs, duplicate normalized UIDs, organizations without
  reliable identifiers, and Supplier-only organizations that must not be forced
  into Customer.
- Every current helper/API caller, including external dotted paths, gateway
  callbacks, imports, reports, permission hooks, and scheduled jobs.

The audit must not merge or mutate records automatically. It persists one
fingerprinted result per site and model version so enforcement cannot rely on a
transient report or an assertion that another environment was empty.

### Phase 2: Introduce the target schema

- Add nullable subject type, direct Contact, identity status, and canonical-alias
  fields to Member and Donor.
- Add Contact identity kind plus nullable Customer/Supplier canonical Contact,
  active organization key, identity status, and canonical-alias fields through
  Good Connector.
- Add Dynamic Link identity-projection provenance fields through Good Connector
  without replacing app-specific relationship-role metadata.
- Add nullable Volunteer Contact and alias fields without renaming existing rows
  yet.
- Add Household Person alongside the old Household Member model. Do not remove
  or reset old rows in schema introduction.
- Add Membership scope, Household, billing Customer, and covered-Member schema
  alongside the compatibility flag.
- Add the proposed Donation Customer and accounting-party fields without
  changing posting behavior yet.
- Add Party Link audit/reporting before enabling strict one-to-one validation.
- Good Connector introduces `GC Identity Migration Run` plus flat
  `GC Identity Migration Issue` records linked to the run, so large migrations
  do not store thousands of issues in one child table. They contain model
  version, phase status, source/target counts, fingerprints, restart cursor,
  operator decisions, and activation flags. non_profit appends its
  role/Household/Donation domain sections through an explicit service contract
  rather than creating a second migration-state store. Both DocTypes have real
  Python controllers and explicit restricted permissions.
- Transfer legal-form/UID ownership according to section 13 without creating,
  deleting, or renaming competing Custom Fields.
- Keep fields nullable during backfill.
- Keep every validator in compatibility mode. Merely migrating schema must not
  reject old records or change creation/accounting behavior.

### Phase 2.5: Resumable backfill and remediation

Run a dedicated, idempotent, resumable service per site. It is not a DocType
event hook and does not commit per record. Batches have deterministic boundaries,
savepoints, source fingerprints, and restart cursors; controlled standalone jobs
commit successful batches and leave blocking issues durable for review.

Automatic backfill is limited to deterministic evidence:

- Adopt an exact single role-linked Contact only when subject type, Customer
  type, Contact identity kind, and all other role links agree.
- Infer Organization only from a Company/Partnership Customer; infer Individual
  only from a proven Person Contact or Individual Customer.
- Never choose the first email, first Dynamic Link, newest record, or fuzzy
  match. Those cases create migration issues.
- Backfill accounting-master canonical Contacts, role direct Contacts, managed
  Dynamic Link projections, alias status, and normalized verified UID evidence.
- Relink legacy personal Addresses to Person Contact and organization Addresses
  to Customer/Supplier without deleting the source role link until equivalence
  is verified.
- Convert Household rows through the conditional conversion fallback when any
  data exists; preserve old rows until count/date/primary/Dynamic-Link checks
  pass.
- Review inferred household Memberships as specified in section 7.4; do not
  invent contractual coverage.
- Backfill every existing Donation to its explicit legacy Donor regime before
  any Customer-regime activation.
- Wrap bulk Contact/Address/Customer/Supplier writes in Good Connector duplicate
  scan suppression and queue one full reconciliation only after a successful
  batch transaction. Dry runs queue nothing.

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
- Introduce one financial-projection service that creates or reuses an
  Individual Customer from canonical Contact at approved triggers.
- Make Customer/Supplier pairing reuse the same canonical Contact for
  individuals and validated legal identity for organizations.
- Keep Supplier-only creation valid; do not create Customer without a
  receivable-side trigger.
- Maintain managed Contact Dynamic Link projections transactionally and resolve
  role form Contact/Address displays from canonical anchors.
- Update Good NPO signup, public donation, imports, demo seeds, and all Desk/API
  helpers to use the same services.
- Update Ilanga to create separate person identities and Contact-based Household
  rows; do not recreate the shared-couple Individual Customer.
- Update the Household controller, Ilanga importer, Good NPO signup consumer,
  reports, docs, and tests behind the migration-version gate. Compatibility
  readers remain until every deployed site completes conversion; no code may
  write both models independently.
- Implement explicit Membership scope and covered-Member validation without
  treating Household residence as coverage.
- Preserve MiKi's organization-only `Membership -> Member -> Customer` contract
  and reject non-Organization Members or Individual Customers at both campaign
  and declaration boundaries. Preserve parent campaign targets, child Customer
  hierarchy, child-specific memberships, and declaration-item generation.
- Log ambiguous matches for manual review instead of selecting the first record.
- Preserve existing helper signatures through compatibility adapters and emit
  the established telemetry for deprecated paths.

### Phase 4: Build consolidation and split controls

- Add read-only dependency previews for Contact, Customer, Supplier, Member, and
  Donor/Volunteer consolidation or split.
- Implement the no-ledger merge versus archived-alias policy from section 9.
- Reconcile role dependencies explicitly rather than delegating the complete
  operation to `rename_doc(merge=True)`.
- Record source IDs, decisions, counts, conflicts, operator, and effective date.
- Add explicit Household separation as a dated relationship operation.
- Restrict preview to users who can read every surfaced record. Restrict
  execution to `System Manager` or `Good Admin` with write access to all
  affected domain records; accounting-party operations additionally require
  `Accounts Manager` or `System Manager`.
- Make previews redact records the operator cannot read and never expose PII
  through dependency counts or error text.

### Phase 5: Enforce identity invariants

This phase is a separate per-site activation command. It refuses to run unless
the persisted migration run matches the installed model version, has zero
blocking issues, reconciles all counts/fingerprints, and the required cross-app
verification suite passed for the release. It locks the activation/settings row,
rechecks invariants under lock, creates or enables database indexes, then records
the enforcement version. Failure leaves compatibility mode active.

- Enforce one active canonical Individual Customer per canonical Contact;
  archived accounting aliases are excluded and blocked from new activity.
- Require canonical Contact on every active non-anonymous Individual Customer
  and Individual Supplier.
- Enforce one Individual Supplier per canonical Contact.
- Enforce one active Individual Member and one active Individual Donor per
  canonical Contact.
- Enforce one active Organization Member and one active Organization Donor per
  organization Customer.
- Require subject type on every active Member and Donor.
- Require Contact on Individual Member and Donor, except the explicitly marked
  anonymous system Donor.
- Require Customer for Organization roles but keep it optional for Individual
  roles until a financial trigger.
- Require an Individual role's Customer, when present, to be an Individual
  Customer anchored to the same canonical Contact.
- Require an Organization role's Customer to be Company or Partnership.
- Enforce one Volunteer per canonical Contact.
- Enforce one current Household per Contact and one current primary person per
  Household.
- Require Person identity kind for Individual roles, accounting projections,
  Volunteers, and Household people; Generic Endpoint and Unclassified cannot
  satisfy those links.
- Require managed Dynamic Link projections to agree with direct canonical
  fields, and require Address relocation verification before retiring role-only
  links.
- Enforce explicit Membership scope and covered-Member overlap rules.
- Enforce verified-UID uniqueness for active organization Customers while
  leaving unidentified organizations review-based.
- Enforce alias lifecycle fields, disabled state where available, canonical
  target type, and new-activity blocks.
- Enable strict one-to-one Party Link validation only after Customer/Supplier
  links and canonical Contacts have been audited and backfilled.
- Remove `Customer.household`, role-owned household state, and inferred
  `Membership.is_household_membership` only after Household and Membership
  migration is complete on every supported site. Explicit Household scope does
  not require joint invoicing; billing remains separately gated.

### Phase 6: Align Donation accounting

Execute only if Customer-based Donation accounting is approved.

- Complete and persist the all-Donation legacy-regime backfill from section 8.1.
- Update new Payment Entry construction and reconciliation to dispatch from the
  stored regime.
- Add and test the narrow Customer-reference Payment Entry mixin with HRMS and
  keep all existing invariants in doc-events.
- Freeze the Donation accounting party on insert/submit as defined in section
  8.1.
- Keep historical Donor party references readable and prevent mixed allocation.
- Verify Donation outstanding amounts, receipts, QRR matching, bank
  reconciliation, donor analytics, and statements.
- Activate the explicit per-site cutover version under the locked Settings row;
  do not infer regime from date at runtime.
- Verify Payrexx, manual Payment Entry, QRR/EBICS, cancellation, amendment,
  recurring generation, reconciliation/unreconciliation, receipt, and analytics
  behavior in both regimes before activation.

### Phase 7: Remove legacy paths

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

## 11. Remaining Decision Gates

The proposal leaves these business or deployment questions. Recommended
defaults are not accepted requirements until recorded through the traceability
boundary above:

| # | Question | Recommended default |
|---|---|---|
| 1 | Should all new Donation payments post against Customer? | Yes; retain Donor only as fundraising attribution. |
| 2 | Does any production site contain submitted Donations, receipts, paid state, or accounting history tied to Donor? | Audit every deployed site and every accounting table before choosing a clean cutover or legacy regime. |
| 3 | How are anonymous Donations represented? | One controlled system Donor and Customer with no Contact and a durable anonymous-system marker; never merge identified people into it. |
| 4 | Does a paid Membership create Customer at Subscription creation, invoice creation, or earlier? | Create it before the first Subscription or invoice requires a receivable party. |
| 5 | Can one Household receive a joint membership invoice? | No by default; select one explicit payer Customer if needed. |
| 6 | Can a Donation or tax receipt legally belong to a Household rather than one person or organization? | No by default; aggregate household giving only in reports. |
| 7 | Can a Contact belong to more than one current Household? | No; preserve prior households as dated history. |
| 8 | Is corporate volunteering represented by individual Volunteers linked to an organization? | Yes; defer organization affiliation to Volunteer Engagement. |
| 9 | May accounting parties with submitted ledger history ever be physically merged? | No by default; archive as aliases and route only future activity to the canonical party. |
| 10 | Should NPO-facing UI relabel Customer as Constituent Account? | Optional presentation change; keep the ERPNext DocType and accounting labels intact. |
| 11 | Should `good_connector` become required by `non_profit` for canonical financial-party identity? | Yes, but only through the staged dependency release in section 14; until activation it remains optional. |
| 12 | Which existing Household Memberships have proven contractual coverage? | Treat every inferred flag as review-required unless an approved source-specific mapping proves covered people. |
| 13 | Which organization identifiers besides validated Swiss UID may enforce canonical uniqueness? | None by default; add an identifier only with normalization, authority, and uniqueness rules. |
| 14 | May Person Contacts carry additional generic communication endpoints? | Yes, as separate Generic Endpoint Contacts linked to the relevant organization; never overload the Person identity Contact. |

## 12. Permission And PII Contract

Strict identity must not grant broad access to ERPNext masters. Canonical fields
use a restricted permission level where needed, and public/system services return
only domain record identifiers already authorized for the caller.

| Operation or data | Required access |
|---|---|
| Read ordinary Member/Membership fields | Existing Non Profit role permissions; no automatic Contact/Customer read grant |
| Read canonical Contact/alias fields on Member, Donor, Volunteer | `Non Profit Manager` plus normal Contact read, or `System Manager`; presentation APIs return only approved display snapshots |
| Create/link a person role in Desk | Create on role plus write on selected Contact and Customer, matching current helper policy |
| Public signup/donation | Guest never selects an existing identity by ID; trusted service performs exact matching, rejects ambiguity, and reveals no candidate details |
| Read/edit Household and covered people | `Non Profit Manager` plus normal read/write checks on affected Member/Contact records; no broad PII bypass |
| Identity migration reports/issues | `System Manager` or `Good Admin`; reports redact any record outside the operator's normal read access |
| Consolidate/split Contact or role | `System Manager` or `Good Admin` plus write on every affected record |
| Archive/merge Customer or Supplier, activate accounting cutover | `System Manager`, or `Good Admin` together with `Accounts Manager`, with all affected accounting-master permissions |
| Read migration/audit result | Same authority as execution; immutable audit contains IDs/evidence, never credentials or secret portal tokens |

`ignore_permissions=True` is limited to reviewed migration/system services after
the outer operation has established authority and scope. It is never used to let
a caller name arbitrary Contact, Customer, Supplier, Household, Member, or Donor
records. Tests cover permission-aware lists, direct document reads, Link search,
guest ambiguity, and redaction.

## 13. Legal-Form And UID Field Ownership

The ownership transfer preserves the installed contract exactly before adding
anything new:

- Good Connector becomes the schema owner of existing
  `Customer.business_uid`, `Customer.legal_form`, and `Supplier.legal_form`.
- `Supplier.business_uid` is new and is added only when organization
  Customer/Supplier pairing by UID is accepted; the plan must not describe it as
  an existing MiKi field.
- Existing fieldnames, stored values, legal-form Select options, and Customer
  labels remain unchanged during transfer. No Custom Field is deleted/recreated
  or renamed.
- Good Connector publishes the shared legal-form options and normalization
  helper first. MiKi consumes that definition while retaining MiKi-specific
  portal labels, declared/current snapshots, validation, and workflow behavior.
- MiKi continues ensuring the existing fields until the minimum Good Connector
  version is deployed everywhere. In the next coordinated release, MiKi stops
  owning their schema definitions only after Good Connector setup is known to
  run first. The two apps never ship divergent definitions for one release.
- Setup compares complete field definitions and writes only actual changes.
  Uninstall does not delete shared fields or values used by another installed
  app.
- Migration tests start from a MiKi-owned site, run Good Connector ownership
  adoption, rerun both setups, and prove no value, options, label, modified
  timestamp, or working-tree fixture drift.

## 14. Good Connector Dependency And Release Choreography

Changing Good Connector from optional to required is a coordinated release, not
a one-line hook edit:

1. Release Good Connector first with backward-compatible Contact kind,
   accounting-master identity/alias fields, legal-field adoption, migration
   records, services, and tests. It must still install independently and keep
   ERPNext imports conditional where its own contract requires that.
2. Inventory every `non_profit` site, take normal production backups, install and
   migrate the minimum Good Connector release, and verify its setup before
   changing `non_profit.required_apps`.
3. Release `non_profit` with `required_apps = ["erpnext", "good_connector"]`,
   compatibility-mode schema, backfill services, updated CI, documentation, and
   a deliberate package version bump. The current base-without-connector CI job
   remains until this release, then is replaced by clean-install and upgrade
   matrices with Good Connector installed first.
4. Release affected consumers in dependency order. Update Docker/installer app
   lists and installation order, developer setup, backup/rollback instructions,
   and cross-app version constraints before enabling strict behavior.
5. Run per-site audit/backfill/remediation. Do not activate identity enforcement
   or Customer Donation accounting as part of install/migrate.
6. Activate strict identity, Household conversion, and Donation cutover as
   separately recorded gates after their verification suites pass.

Schema, dependency, API, and installed-behavior changes require coordinated
version decisions under the custom-app versioning policy. Documentation-only
edits to this unaccepted proposal do not themselves bump a package version.

## 15. Affected Apps

| App | Expected impact |
|---|---|
| non_profit | Owns shared role DocTypes, Household, role identity rules, and Donation accounting hooks |
| good_npo | Signup, donor/member creation, Household inheritance, public flows, and navigation |
| miki_app | Keeps the stricter organization Member/Customer contract, campaign selection, declarations, billing, and portal identity |
| ilanga_app | Replace the pre-production shared-couple Customer and role-based Household importer behavior |
| good_analytics | Donor/Customer identity, segmentation, address/contact resolution, and giving aggregation |
| good_demo | Demo Member, Donor, Volunteer, Contact, Customer, and Household fixtures |
| good_event | Optional membership lookup and organization/person Customer creation |
| good_connector | Shared identity matching, duplicate review, canonical financial-party links, and strict Party Link validation |
| payrexx_integration | Direct Donation checkout/settlement contract and both legacy Donor and new Customer Payment Entry regimes |
| good_newsletter | Indirect donor/person audience payload compatibility through Good Analytics and Contact salutations |
| barakah_app | Compatibility check for Supplier-only parties and portal Supplier identities; no forced Customer creation |
| good_mel / barakah_mel | Compatibility check for partner organizations that may be Customer, Supplier, or both |
| goodvantage_app | Compatibility check for global Customer/Supplier fields, Party Link validation, and HRMS Payment Entry MRO |

Changes to Member or Membership semantics must update and verify `miki_app` in
the same implementation change.

## 16. Acceptance Criteria

- Creating Member and Donor roles for the same person reuses one canonical
  Contact without creating Customer prematurely.
- The first financial trigger creates or reuses one Individual Customer for that
  canonical Contact.
- An Organization Member or Donor reuses one Company or Partnership Customer,
  even before financial activity.
- Every active role has a subject type and the required Contact or organization
  Customer; cross-field Customer type and canonical Contact links agree.
- Every person identity anchor is a Contact classified as `Person`; a Generic
  Endpoint or Unclassified Contact cannot satisfy an Individual role,
  accounting projection, Volunteer, or Household Person.
- A canonical Contact cannot identify two Individual Customers or two Individual
  Suppliers.
- The same Contact can remain linked as representative to multiple organization
  Customers and Suppliers.
- One organization Customer can hold Member and Donor roles without duplicated
  Contact or Address records.
- Verified organization UIDs identify at most one active organization Customer;
  unidentified organizations remain review-based without a false uniqueness
  claim.
- Supplier-only parties remain valid and do not create Customer until a
  receivable-side role requires it.
- Volunteer creation reuses the canonical Contact and creates no Customer unless
  another financial role requires one.
- Volunteer identity does not depend on email, and email changes do not create a
  second Volunteer.
- A Household can include a person with no NPO role.
- One person with Member and Donor roles appears once in a Household.
- Household history and current-primary rules remain enforced.
- Current Household Contact Dynamic Links exactly project current Household
  Person rows, while ended rows remain only as history.
- Household separation changes dated relationships without splitting identity
  or moving historical financial documents.
- Household presence alone never changes the payer or invoice scope.
- Household Membership has explicit scope, dated covered Members, one
  administrative Member included in coverage, and no overlapping same-type
  coverage for one person.
- No current inferred household flag is converted to contractual coverage
  without approved evidence.
- Customer/Supplier dual roles use a validated one-to-one Party Link and preserve
  standard ERPNext sales and purchasing behavior.
- MiKi campaign and declaration flows continue to require and resolve exactly
  one Organization Member Customer through
  `Membership -> Member -> Customer`.
- MiKi parent Customers remain campaign targets, child Customers remain
  declaration items, and consolidation does not flatten
  `Customer.parent_organization` or promote child-specific memberships.
- Contact-only Individual Members remain valid in `non_profit` and ineligible
  for MiKi declarations.
- A Donation uses one immutable accounting party regime and can never mix Donor
  and Customer allocations.
- Every Donation Payment Entry matches both the immutable party type and exact
  immutable party for its regime.
- Consolidation provides a dependency preview and never relies on email or name
  as automatic proof.
- Archived accounting aliases remain readable, are linked to the canonical
  identity, and cannot receive new roles or transactions.
- Archived role aliases have the same explicit lifecycle, are excluded from
  normal selectors, and cannot consume active uniqueness keys.
- Splitting an identity moves only supported future/unsubmitted relationships;
  submitted accounting remains historically traceable.
- Existing submitted Payment Entries, GL Entries, Donations, Sales Invoices,
  Journal Entries, Payment Ledger Entries, Memberships, and Subscriptions remain
  traceable after migration, with required historical Party Type records kept.
- Household schema replacement is blocked unless deployed-site preflight proves
  no Household data, `Customer.household` values, role links, direct Contact
  links, or Household Addresses exist; otherwise verified conversion is
  mandatory.
- Required canonical identity behavior has one explicit app owner and no
  optional-import execution path.
- Ambiguous identities enter manual review; no migration silently chooses the
  first matching Customer, Contact, Member, or Donor.
- Direct canonical Contact fields, managed Dynamic Link projections, and
  canonical Address ownership agree after migration; legacy links are not
  removed before equivalent target links are verified.
- A persisted migration run proves source/target counts, fingerprints, zero
  blocking issues, and the active model version before enforcement can turn on.
- Good Connector dependency activation follows the staged release order; clean
  install and upgrade both install it before non_profit.
- Current helper/API paths remain functional adapters until their telemetry and
  release-cycle removal gates are satisfied.

## 17. Verification Matrix

No phase is complete based only on unit tests or acceptance prose. The
implementation release must publish and pass this matrix before per-site
activation.

### 17.1 Install, upgrade, and migration

- Clean install in final dependency order with ERPNext, Good Connector,
  non_profit, and each direct consumer.
- Upgrade from the current `non_profit` model with Good Connector absent, then
  install/adopt Good Connector through the documented release sequence.
- Upgrade sites containing B2C Contact-only Members, B2B organization Members,
  Donors with/without Customer, duplicate Dynamic Links, role-linked Addresses,
  disabled accounting parties, and ambiguous identities.
- Dry-run and applied backfill, interruption between batches, retry after worker
  failure/deadlock, source drift after a reviewed issue, and idempotent rerun.
- Enforcement refusal for stale fingerprint, incomplete counts, unresolved
  issue, wrong model version, missing dependency, or failed verification marker.
- Household empty-site clean replacement and populated-site conversion with
  exact history/date/primary/Address/Contact projection reconciliation.
- MiKi-owned legal field adoption by Good Connector with no metadata/value drift.
- Working-tree cleanliness after install, migrate, and uninstall paths.

### 17.2 Identity and concurrency

- Person versus Generic Endpoint classification and blocked invalid transitions.
- Individual and organization Member/Donor creation, one role per identity,
  Supplier-only parties, and verified-UID organization uniqueness.
- Canonical Contact changes with managed Dynamic Link and Address projection
  reconciliation.
- Concurrent financial projection, role creation, Household move, Party Link,
  archive/reactivate, consolidation, and split. Assert deterministic lock order,
  one winner, no partial writes, and retryable deadlocks.
- Archived alias selector exclusion and new-activity blocking across Membership,
  Donation, Volunteer, Sales/Purchase documents, Payment Entry, imports, and
  public/Desk helpers.

### 17.3 Household and Membership

- Roleless Household people, one current Household, one current primary,
  historical ended rows, separation, and derived Contact Dynamic Links.
- Individual, Organization, and Household Membership scopes; covered-Member
  date bounds, administrative-member inclusion, overlap prevention, renewal,
  mid-term coverage changes, and payer immutability once invoiced.
- Migration of `is_household_membership = 0`, review gating for inferred true
  rows, approved Ilanga source mapping, and refusal to invent coverage.
- Non-ledger joint ask versus legally collectible invoice remains behind the
  selected business decision; tests must not encode both as active behavior.

### 17.4 Donation accounting

- Legacy backfill for every Donation docstatus and state, including manual paid,
  partial allocations, amendments, cancellations, receipts, and recurring rows.
- Customer-regime insert after activation, old draft submit after activation,
  amendment regime inheritance, immutable exact party validation, and mixed
  allocation rejection.
- Effective Payment Entry class/MRO with HRMS, `super()` behavior, Employee and
  standard Customer/Supplier references, current doc-event invariants, partial
  settlement, cancellation, and reconciliation/unreconciliation.
- Payrexx checkout and callback settlement, manual Payment Entry, EBICS/QRR
  candidate matching, Bank Transaction linking, Donation receipts, statements,
  outstanding, roll-ups, Good Analytics, and Good Newsletter audiences in both
  regimes.
- Historical Member/Donor Party Type rows remain readable after new-use
  registration stops.

### 17.5 Cross-app and security

- Full focused suites for non_profit, Good Connector, Good NPO, MiKi, Ilanga,
  Good Analytics, Good Demo, Good Event, Payrexx Integration, and Good
  Newsletter, plus compatibility smoke tests for Supplier/Party Link consumers.
- MiKi campaign/readiness/declaration/invoice behavior with only Organization
  Members, preserved parent/child Customers, and passive Individual Members
  excluded from declarations.
- Good Demo ownership/privacy queries after identity fields replace email-based
  role resolution.
- Permission matrix coverage for Desk roles, Contact/Address/User Permissions,
  migration reports, consolidation, accounting activation, guest ambiguity,
  redaction, and direct API access.
- Compatibility telemetry proves old helper signatures and payloads continue to
  work before any removal clock starts.

## 18. Explicit Non-Goals

- Do not modify ERPNext or Frappe core DocTypes directly.
- Do not collapse Customer and Supplier into one custom accounting party.
- Do not create one Customer per role, accounting Company, campaign, or app.
- Do not use email as the permanent identity key.
- Do not rewrite submitted ledger history as part of identity cleanup.
- Do not represent a couple or Household by sharing one Individual Customer.
- Do not represent an organization as a person Contact; organization Contacts
  are representatives or communication endpoints.
- Do not introduce a generic Constituent DocType unless Household financial
  identity or another approved requirement cannot be represented safely with
  Customer, Supplier, Contact, and Household.
