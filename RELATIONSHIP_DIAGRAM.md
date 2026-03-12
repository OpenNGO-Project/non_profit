# Non Profit Relationship Diagram

## High-Level Refactored Model

This is the simplified business view of the current refactored model:

- `Customer` is the canonical legal and billing party.
- `Member` is the nonprofit profile of exactly one `Customer`.
- `Membership` belongs to a `Member`.
- `Contact` and `Address` stay attached to `Customer` through Frappe's dynamic linking model.
- `Subscription` and `Sales Invoice` remain the ERPNext billing objects.
- `Lead` is the prospect record and can convert into `Customer`.

### ASCII Overview

```text
                    +------------------+
                    |     Contact      |
                    |------------------|
                    | human contact    |
                    | is_primary...    |
                    +---------+--------+
                              ^
                              | Dynamic Link
                              |
+------------------+          |          +------------------+
|     Address      |----------+--------->|     Customer     |
|------------------| Dynamic Link        |------------------|
| billing/shipping |                     | legal/billing    |
+------------------+                     | party            |
                                         | customer_type    |
                                         +---------+--------+
                                                   ^
                                                   | 1:1
                                                   |
                                         +---------+--------+
                                         |      Member      |
                                         |------------------|
                                         | nonprofit profile|
                                         | member_name      |
                                         | derived          |
                                         | designated_rep ? |
                                         +---------+--------+
                                                   ^
                                                   | 1:n
                                                   |
                                         +---------+--------+
                                         |    Membership    |
                                         |------------------|
                                         | membership_type  |
                                         | billing customer |
                                         | billing contact  |
                                         | auto_renew       |
                                         | subscription     |
                                         +---------+--------+
                                                   |
                                                   | 0..1
                                                   v
                                         +---------+--------+
                                         |   Subscription   |
                                         |------------------|
                                         | party=Customer   |
                                         | plans/status     |
                                         +---------+--------+
                                                   |
                                                   | 1:n
                                                   v
                                         +------------------+
                                         |   Sales Invoice  |
                                         |------------------|
                                         | customer         |
                                         | contact_person   |
                                         | customer_address |
                                         | subscription     |
                                         +------------------+

Lead -> Customer conversion happens before this chain.
```

```mermaid
flowchart LR
    LEAD[Lead]
    CUSTOMER[Customer<br/>legal and billing party]
    MEMBER[Member<br/>nonprofit profile]
    MEMBERSHIP[Membership<br/>entitlement]
    CONTACT[Contact<br/>human contact]
    ADDRESS[Address]
    SUBSCRIPTION[Subscription<br/>billing engine]
    SALES_INVOICE[Sales Invoice]

    LEAD -->|converts to| CUSTOMER
    CUSTOMER -->|1:1| MEMBER
    MEMBER -->|1:n| MEMBERSHIP
    CUSTOMER -->|linked contacts| CONTACT
    CUSTOMER -->|linked addresses| ADDRESS
    MEMBER -. optional designated representative .-> CONTACT
    MEMBERSHIP -->|billing customer| CUSTOMER
    MEMBERSHIP -->|billing contact| CONTACT
    MEMBERSHIP -->|auto-renew via| SUBSCRIPTION
    SUBSCRIPTION -->|party| CUSTOMER
    SUBSCRIPTION -->|generates| SALES_INVOICE
    SALES_INVOICE -->|customer| CUSTOMER
    SALES_INVOICE -.->|invoice contact| CONTACT
```

## Relationship Notes

- `Lead -> Customer`: conversion path from prospect to party record.
- `Customer -> Member`: 1:1 nonprofit profile relationship.
- `Member -> Membership`: one member can hold multiple memberships.
- `Customer -> Contact` and `Customer -> Address`: handled through Frappe `Dynamic Link` records.
- `Member -> Contact`: optional designated representative, mainly useful for organizations.
- `Membership -> Customer` and `Membership -> Contact`: explicit billing fields on the membership.
- `Membership -> Subscription -> Sales Invoice`: billing chain for renewals and invoices.
- `Sales Invoice -> Contact`: invoice-specific contact person, not ownership.

## Technical ER Diagram

```mermaid
erDiagram
    LEAD ||--o| CUSTOMER : converts_to
    CUSTOMER ||--|| MEMBER : profiles_as
    MEMBER ||--o{ MEMBERSHIP : has
    MEMBERSHIP o|--|| CUSTOMER : bills_to
    MEMBERSHIP o|--|| CONTACT : bills_to_contact
    MEMBERSHIP o|--o| SUBSCRIPTION : renews_via
    SUBSCRIPTION }o--|| CUSTOMER : party
    SUBSCRIPTION ||--o{ SALES_INVOICE : generates
    SALES_INVOICE }o--|| CUSTOMER : invoices
    SALES_INVOICE }o--o| CONTACT : invoice_contact
    CUSTOMER }o--o{ CONTACT : linked_via_dynamic_link
    CUSTOMER }o--o{ ADDRESS : linked_via_dynamic_link
    MEMBER }o--o| CONTACT : designated_representative
    LEAD }o--o{ CONTACT : linked_via_dynamic_link
    LEAD }o--o{ ADDRESS : linked_via_dynamic_link

    LEAD {
        string name
        string lead_name
        string company_name
        string email_id
        string customer
    }

    CUSTOMER {
        string name
        string customer_name
        string customer_type
        string lead_name
    }

    MEMBER {
        string name
        string member_name
        string customer
        string designated_representative
        string primary_chapter
    }

    MEMBERSHIP {
        string name
        string member
        string member_name
        string membership_type
        string customer
        string contact
        string subscription
        string subscription_status
    }

    CONTACT {
        string name
        string full_name
        string email_id
        int is_primary_contact
    }

    ADDRESS {
        string name
        string address_type
        int is_primary_address
    }

    SUBSCRIPTION {
        string name
        string party_type
        string party
        string status
    }

    SALES_INVOICE {
        string name
        string customer
        string contact_person
        string customer_address
        string subscription
    }
```
