# Frappe Framework & ERPNext Developer Agent Configuration

## 1. Persona & Role
- **Role:** Senior Frappe Framework Developer & ERPNext Architect
- **Objective:** Develop scalable, upgrade-safe, performant, and maintainable applications
- **Tone:** Technical, precise, authoritative on "The Frappe Way"

---

## 2. The "Frappe Way" (Core Philosophies)

### Upgrade Safety
- **Never modify core files** (`apps/frappe`, `apps/erpnext`)
- Use: Custom Apps, Hooks, Property Setters, Customization via Export
- All customizations must be exportable to a custom app via "Export Customizations"

### Metadata First
- Leverage DocType configurations before writing code
- Use Custom Fields, Property Setters, Client Scripts for simple customizations
- Only write Python/JS when DocType configuration is insufficient

### Server-Side Authority
- **Always** validate data in Python controllers (JS validation is UX only, not security)
- Business logic belongs server-side; client-side is for UX enhancement

### Reuse Before Create
- Check `frappe.utils`, `frappe.db`, existing standard DocTypes first
- Common patterns: User, Employee, Customer, Supplier, Item, etc.

---

## 3. Technical Constraints & Coding Standards

### Python (Server-Side)

#### ORM & Database API
```python
# Full document (use when you need all fields or to modify)
doc = frappe.get_doc(doctype, name)

# Single value - fastest for simple reads
value = frappe.db.get_value(doctype, name, fieldname)
# Returns: "value" or {"field1": "val1", "field2": "val2"} if multiple fields

# List of documents - lightweight
docs = frappe.get_all(doctype, filters={}, fields=['name', 'title'], limit=10)

# Query Builder (PREFER over raw SQL for complex queries)
from frappe.query_builder.functions import Count
from frappe.query_builder import DocType, Field

doctype = DocType('Sales Order')
query = (
    frappe.qb.from_(doctype)
    .select(doctype.name, doctype.customer)
    .where(doctype.status == 'Draft')
    .orderby(doctype.creation, order=frappe.qb.desc)
)
results = query.run()

# Raw SQL - LAST RESORT, always parameterized
frappe.db.sql("SELECT name FROM `tabSales Order` WHERE customer = %s", (customer,), as_dict=True)
```

#### Controller Pattern
```python
import frappe
from frappe.model.document import Document

class SalesOrder(Document):
    def validate(self):
        self.calculate_totals()
        self.validate_customer_credit()
    
    def before_save(self):
        self.set_missing_values()
    
    def on_submit(self):
        self.create_sales_invoice()
    
    def on_cancel(self):
        self.cancel_related_docs()
    
    def on_trash(self):
        pass  # cleanup before deletion
    
    def calculate_totals(self):
        total = sum(item.amount for item in self.items)
        self.total = total
```

#### Whitelisting & Security
```python
# Methods called from client must be whitelisted
@frappe.whitelist()
def get_customer_details(customer):
    # Validate permissions
    if not frappe.has_permission('Customer', 'read', customer):
        frappe.throw(frappe._("No permission to access Customer"))
    
    return frappe.get_doc('Customer', customer).as_dict()

# For methods accepting complex data
@frappe.whitelist()
def process_items(items):
    # frappe.parse_json handles JSON string conversion
    if isinstance(items, str):
        items = frappe.parse_json(items)
```

#### Translations
```python
# Always wrap user-facing strings
frappe.throw(frappe._("Total cannot be negative"))
message = frappe._("Document {0} created successfully").format(doc.name)
```

### JavaScript (Client-Side)

#### Form Scripts
```javascript
frappe.ui.form.on('Sales Order', {
    refresh: function(frm) {
        // Add custom buttons only in appropriate states
        if (frm.doc.docstatus === 1 && !frm.doc.status === 'Closed') {
            frm.add_custom_button(__('Create Invoice'), () => {
                frappe.model.open_mapped_doc({
                    method: 'create_invoice_from_order',
                    source_name: frm.doc.name
                });
            }, __('Create'));
        }
        
        // Hide fields conditionally
        frm.toggle_display('internal_section', frm.doc.is_internal);
    },
    
    customer: function(frm) {
        if (frm.doc.customer) {
            // Use frappe.db.get_value for single fetches
            frappe.db.get_value('Customer', frm.doc.customer, 'credit_limit')
                .then(r => {
                    if (r.message) {
                        frm.set_value('credit_limit', r.message.credit_limit);
                    }
                });
        }
    },
    
    // Child table events
    items_add: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        row.idx = frm.doc.items.length;  // Set row index
    },
    
    items_on_form_rendered: function(frm) {
        // Trigger after child table row form opens
    },
    
    validate: function(frm) {
        // Client-side validation (UX only - also validate server-side)
        if (frm.doc.items && frm.doc.items.length === 0) {
            frappe.msgprint(__('Please add at least one item'));
            frappe.validated = false;
        }
    }
});

// Child table field events
frappe.ui.form.on('Sales Order Item', {
    item_code: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        // Fetch and set item details
        frappe.db.get_value('Item', row.item_code, ['item_name', 'stock_uom'])
            .then(r => {
                if (r.message) {
                    frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
                    frappe.model.set_value(cdt, cdn, 'uom', r.message.stock_uom);
                }
            });
    },
    
    qty: function(frm, cdt, cdn) {
        calculate_row_amount(frm, cdt, cdn);
    },
    
    rate: function(frm, cdt, cdn) {
        calculate_row_amount(frm, cdt, cdn);
    }
});

function calculate_row_amount(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    var amount = (row.qty || 0) * (row.rate || 0);
    frappe.model.set_value(cdt, cdn, 'amount', amount);
}
```

#### Server Calls
```javascript
// Using frappe.call with promise
frappe.call({
    method: 'my_app.api.get_data',
    args: {
        param1: 'value1',
        param2: 'value2'
    }
}).then(r => {
    if (r.message) {
        console.log(r.message);
    }
});

// Using async/await
async function fetchData() {
    const r = await frappe.call({
        method: 'my_app.api.get_data',
        args: { param: 'value' }
    });
    return r.message;
}
```

---

## 4. Directory Structure

```
apps/
├── custom_app/
│   ├── hooks.py              # Central event/override configuration
│   ├── modules.txt           # List of modules
│   ├── patches.txt           # Database migration patches
│   ├── custom_app/
│   │   ├── doctype/
│   │   │   └── my_doctype/
│   │   │       ├── my_doctype.json    # DocType metadata
│   │   │       ├── my_doctype.py      # Controller
│   │   │       ├── my_doctype.js      # Client script
│   │   │       ├── test_my_doctype.py # Unit tests
│   │   │       └── README.md          # Documentation
│   │   ├── page/
│   │   │   └── my_page/
│   │   ├── report/
│   │   │   └── my_report/
│   │   └── api.py            # API endpoints
│   ├── templates/
│   │   ├── pages/            # Jinja pages
│   │   └── includes/         # Reusable templates
│   └── public/
│       ├── js/               # Frontend JS
│       └── css/              # Stylesheets
└── sites/
    └── [site_name]/
        ├── site_config.json  # Site configuration
        └── logs/             # Log files
```

---

## 5. Hooks Configuration (hooks.py)

```python
# DocType event hooks
doc_events = {
    'Sales Order': {
        'before_submit': 'my_app.handlers.validate_sales_order',
        'on_submit': 'my_app.handlers.create_invoice',
        'on_cancel': 'my_app.handlers.handle_cancellation'
    }
}

# Scheduled tasks
scheduler_events = {
    'daily': [
        'my_app.tasks.daily_cleanup',
        'my_app.tasks.send_daily_report'
    ],
    'hourly': [
        'my_app.tasks.hourly_sync'
    ],
    'cron': {
        '0 0 * * 0': 'my_app.tasks.weekly_report'  # Every Sunday at midnight
    }
}

# Override standard methods
override_doctype_class = {
    'Sales Invoice': 'my_app.overrides.CustomSalesInvoice'
}

# JavaScript/CSS includes
app_include_js = '/assets/my_app/js/my_app.js'
app_include_css = '/assets/my_app/css/my_app.css'

# Whitelisted methods (for REST API access without authentication)
whitelisted_methods = [
    'my_app.api.public_endpoint'
]

# Permission query conditions
permission_query_conditions = {
    'Sales Order': 'my_app.permissions.get_sales_order_conditions'
}
```

---

## 6. Common Gotchas & Anti-Patterns

### Creating New DocTypes
- **Always define the Python controller class** - never leave it commented out
- If the class is missing or commented, `bench migrate` will mark the DocType as "orphan" and delete it
- This creates a vicious cycle: import fails -> orphan -> deleted -> next migrate re-imports -> fails again
```python
# WRONG - causes DocType to be deleted as orphan
# class MyDocType(Document):
#     pass

# CORRECT - actual class definition required
class MyDocType(Document):
    pass  # Can be empty, but must exist
```
- For child tables (istable=1), the same rule applies - the controller class must exist

### Naming
- Document naming via `naming_series` or `autoname` in DocType
- **Never** manually set `doc.name` unless `autoname` is `Prompt` or field-based

### Date Handling
```python
from frappe.utils import getdate, add_days, today, now_datetime, get_datetime

# CORRECT
if getdate(doc.delivery_date) < getdate(today()):
    frappe.throw(_("Delivery date cannot be in the past"))

# WRONG - string comparison is unreliable
if doc.delivery_date < today():  # Don't do this
```

### Permissions
```python
# Check permission before operations
if not frappe.has_permission('Sales Order', 'write', doc.name):
    frappe.throw(frappe._("No permission to modify this document"))

# Document-level check
if not doc.has_permission('read'):
    frappe.throw(frappe._("No access"))

# Avoid ignore_permissions unless absolutely necessary (background jobs)
doc.save(ignore_permissions=True)  # Use sparingly
```

### Transactions
```python
# NEVER call commit() in DocType events - breaks atomic transactions
# CORRECT - let Frappe handle it
def on_submit(self):
    self.create_related_doc()  # Frappe commits automatically

# ONLY use commit() in standalone scripts/commands
def manual_data_migration():
    for batch in batches:
        process_batch(batch)
        frappe.db.commit()  # Periodic commits in long-running scripts
```

### Error Handling
```python
# frappe.throw() - stops execution, rolls back transaction
frappe.throw(frappe._("Invalid data"))  # ValidationError

# frappe.msgprint() - shows message, continues execution
frappe.msgprint(frappe._("Processing complete"))

# Log for debugging (not user-facing)
frappe.log_error(f"Debug: {data}", "Custom Debug")
```

---

## 7. Development Workflow

| Change Type | Command Required |
|-------------|------------------|
| DocType JSON changes | `bench migrate` |
| Python code changes | `bench restart` |
| JS/CSS changes (dev) | `bench watch` (auto-reload) |
| JS/CSS changes (prod) | `bench build` |
| Hooks changes | `bench restart` |
| Install/update app | `bench --site [site] install-app [app]` |
| Run tests | `bench --site [site] run-tests --app [app]` |
| Console | `bench --site [site] console` |
| Execute script | `bench --site [site] execute path/to/script.py` |

---

## 8. Testing

```python
import frappe
from frappe.tests.utils import FrappeTestCase

class TestSalesOrder(FrappeTestCase):
    def setUp(self):
        # Runs before each test
        frappe.set_user("Administrator")
    
    def tearDown(self):
        # Runs after each test
        frappe.db.rollback()  # Clean up test data
    
    def test_sales_order_creation(self):
        so = frappe.get_doc({
            'doctype': 'Sales Order',
            'customer': '_Test Customer',
            'delivery_date': frappe.utils.add_days(frappe.utils.today(), 7),
            'items': [{
                'item_code': '_Test Item',
                'qty': 1,
                'rate': 100
            }]
        })
        so.insert()
        so.submit()
        
        self.assertEqual(so.docstatus, 1)
        self.assertEqual(so.status, 'To Deliver')
    
    def test_validation_error(self):
        so = frappe.get_doc({
            'doctype': 'Sales Order',
            'customer': '_Test Customer'
            # Missing required fields
        })
        
        with self.assertRaises(frappe.ValidationError):
            so.save()
```

Run tests:
```bash
bench --site [site] run-tests --app my_app
bench --site [site] run-tests --doctype "Sales Order" --test "test_sales_order_creation"
```

---

## 9. Performance Tips

1. **Use `frappe.db.get_value`** for single values instead of `frappe.get_doc`
2. **Batch operations** using `frappe.db.bulk_insert` or bulk_update
3. **Index frequently queried fields** via DocType configuration
4. **Use Query Builder** (`frappe.qb`) for complex queries
5. **Cache expensive computations**:
```python
@frappe.cache(ttl=3600)
def get_expensive_data(key):
    return compute_something(key)
```
6. **Avoid N+1 queries** - fetch related data in single query

---

## 10. Debugging & Logging

```python
# Log to Error Log
frappe.log_error(f"Error details: {str(e)}", "My App Error")

# Log to specific doctype
frappe.get_doc({
    'doctype': 'Error Log',
    'method': 'my_function',
    'error': str(e)
}).insert()

# Debug in console
# bench --site [site] console
>>> import frappe
>>> doc = frappe.get_doc('Sales Order', 'SO-001')
>>> print(doc.as_dict())

# Print debug (development only)
print(frappe.as_json(data))  # Check terminal output
```

---

## 11. Quick Reference Links

- **Official Docs:** https://frappeframework.com/docs
- **API Reference:** https://frappeframework.com/docs/user/en/api
- **Hooks:** https://frappeframework.com/docs/user/en/python-api/hooks
- **Query Builder:** https://frappeframework.com/docs/user/en/api/query-builder
- **Forum:** https://discuss.frappe.io

---

## 12. Workspaces & Sidebars

### Workspace vs Sidebar (Important Distinction)
- **Workspace**: The main page content (number cards, charts, shortcuts, link cards at bottom)
- **Workspace Sidebar**: The left navigation panel that appears when inside a workspace
- These are **separate DocTypes** with different JSON structures

### Workspace Structure (`workspace/xxx/xxx.json`)
```json
{
	"doctype": "Workspace",
	"title": "My Workspace",
	"content": "[{\"type\":\"header\"},{\"type\":\"number_card\"},{\"type\":\"shortcut\"},{\"type\":\"card\"}]",
	"links": [
		{"type": "Card Break", "label": "Section Name"},
		{"type": "Link", "label": "DocType Name", "link_to": "DocType Name", "link_type": "DocType"}
	],
	"shortcuts": [
		{"label": "New Item", "link_to": "Item", "type": "DocType", "color": "#e03c31"}
	]
}
```

### Workspace Sidebar Structure (`workspace_sidebar/xxx.json`)
```json
{
	"doctype": "Workspace Sidebar",
	"title": "My Sidebar",
	"header_icon": "users",
	"items": [
		{"type": "Link", "label": "Home", "link_to": "Workspace Name", "link_type": "Workspace", "icon": "home"},
		{"type": "Section Break", "label": "Section Name", "icon": "users"},
		{"type": "Link", "label": "Member", "link_to": "Member", "link_type": "DocType", "icon": "user", "child": 1}
	]
}
```

### Sidebar Item Properties
- `type`: "Link" or "Section Break"
- `child`: 0 = section header, 1 = item under previous section
- `link_type`: "DocType", "Workspace", "Report", "Page"
- `icon`: Use Frappe icon names (home, users, user, cog, etc.)
- `indent`: 0 = top level, 1+ = indented

### Directory Structure
```
app/
├── workspace/
│   └── my_workspace/
│       └── my_workspace.json
└── workspace_sidebar/
    └── my_sidebar.json
```

### Importing Workspace/Sidebar Updates
If changes to JSON files don't appear after `bench migrate`:
```python
# Delete and reimport
frappe.delete_doc("Workspace Sidebar", "My Sidebar")
frappe.db.commit()

from frappe.modules.import_file import import_file_by_path
import_file_by_path("/path/to/workspace_sidebar/my_sidebar.json")
frappe.db.commit()
```

### Number Cards (`number_card/xxx/xxx.json`)
```json
{
	"doctype": "Number Card",
	"label": "Total Members",
	"document_type": "Member",
	"type": "Document Count",
	"filters_json": "[]",
	"is_public": 1
}
```

For aggregations:
```json
{
	"type": "Sum",
	"aggregate_function_based_on": "amount",
	"filters_json": "[[\"Donation\",\"date\",\"Timespan\",\"this year\",false]]"
}
```

---

## 13. JavaScript Gotchas

### String Formatting
```javascript
// WRONG - Python style format doesn't work in JS
__("Added {0} recipients.").format([count])  // TypeError: format is not a function

// CORRECT - Use replace
__("Added {0} recipients.").replace("{0}", count)

// Or use template literals
`${__("Added")} ${count} ${__("recipients.")}`
```

### MultiSelectDialog Callback
```javascript
new frappe.ui.form.MultiSelectDialog({
	doctype: "Contact",
	action: function(selected_documents, args) {
		// selected_documents = array of record names ["CNT-001", "CNT-002"]
		// args = additional filter values
		console.log(selected_documents);  // NOT "selections"
	}
});
```

### frappe.call Response
```javascript
frappe.call({
	method: "my_app.api.get_data",
	args: { param: "value" }
}).then(r => {
	// Response is in r.message, NOT r directly
	console.log(r.message);
});
```

---

## 14. DocType Layout Debugging

### Orphan Fields Cause Layout Issues
If a field exists in `fields` array but NOT in `field_order`, it becomes an "orphan" and can cause:
- Empty columns in new document forms
- Unpredictable layout behavior
- Works fine when document has values (appears cached)

### Always Start with Section Break
```json
{
	"field_order": [
		"section_break_main",  // Required first!
		"title",
		"column_break_main",
		"status"
	],
	"fields": [
		{"fieldname": "section_break_main", "fieldtype": "Section Break"},
		{"fieldname": "title", "fieldtype": "Data"},
		{"fieldname": "column_break_main", "fieldtype": "Column Break"},
		{"fieldname": "status", "fieldtype": "Select"}
	]
}
```

### Sync JSON to Database
After fixing DocType JSON:
```bash
bench --site [site] reload-doctype "DocType Name" --app my_app
bench --site [site] clear-cache
bench restart
```

---

## 15. Python Dict Access in Templates

When passing data to templates or functions:
```python
# WRONG - attribute access on dict
context = {"email": recipient.email, "name": recipient.name}  # If recipient is a dict
message = context.email  # AttributeError

# CORRECT - bracket notation
context = {"email": recipient["email"], "name": recipient["name"]}
message = context["email"]
```

This is especially important when working with `frappe.get_all()` results:
```python
recipients = frappe.get_all("Email Group Member", fields=["email", "first_name"])
for recipient in recipients:
	# recipient is a dict, use recipient["email"] not recipient.email
	email = recipient["email"]
```

---

## 16. Fixing Broken Imports in Existing Apps

When an existing app has broken imports:
```python
# Original broken import in donation.py
from non_profit.non_profit.doctype.membership.membership import verify_signature

# If verify_signature doesn't exist in membership.py, either:
# 1. Add the function to membership.py, or
# 2. Add the function locally to the file that needs it

def verify_signature(body, endpoint='Donation'):
	"""Verify Razorpay webhook signature."""
	signature = frappe.get_request_header('X-Razorpay-Signature')
	# ... implementation
```

---

## 17. Cache Clearing for UI Changes

When workspace/sidebar changes don't appear:
```bash
# Clear all cache
bench --site [site] clear-cache

# Clear user-specific cache
bench --site [site] execute "frappe.cache_manager.clear_user_cache('user@example.com')"

# Hard refresh browser: Ctrl+Shift+R or Cmd+Shift+R
```

---

## 18. Permission System

### Permission Query Conditions (`hooks.py`)

Custom permission filtering via SQL WHERE clauses:

```python
permission_query_conditions = {
    "Member": "non_profit.non_profit.permissions.get_member_query_condition",
    "Chapter": "non_profit.non_profit.permissions.get_chapter_query_condition",
    "Membership": "non_profit.non_profit.permissions.get_membership_query_condition",
    "Subscription": "non_profit.non_profit.permissions.get_subscription_query_condition",
    "Sales Invoice": "non_profit.non_profit.permissions.get_sales_invoice_query_condition",
    "Contact": "non_profit.non_profit.permissions.get_contact_query_condition",
    "Address": "non_profit.non_profit.permissions.get_address_query_condition",
}
```

**Implementation pattern:**

```python
def get_member_query_condition(user: str) -> str:
    # Always check for full access users first
    if user == "Administrator":
        return ""
    
    if "Non Profit Manager" in frappe.get_roles(user):
        return ""
    
    # No accessible chapters = no access
    accessible_chapters = get_user_accessible_chapters(user)
    if not accessible_chapters:
        return "1=0"
    
    # Return SQL WHERE clause
    chapter_list = "', '".join([c.replace("'", "''") for c in accessible_chapters])
    return f"`tabMember`.`primary_chapter` IN ('{chapter_list}')"
```

**Returns:**
- `""` = full access (no restriction)
- `"1=0"` = no access
- SQL WHERE clause = filtered access

### User Permissions System

- Stored in `tabUser Permission` table
- Key fields: `user`, `allow` (DocType), `for_value` (record name), `access_level`
- **Native Frappe behavior**: Only restricts Link fields pointing to the `allow` DocType
- **Does NOT cascade** to related doctypes automatically - requires custom `permission_query_conditions`

### Extended Permission Queries for Related DocTypes

When a user has Chapter permissions, extend access to related doctypes via `permission_query_conditions`:

**Subscription permission must check multiple paths:**
1. Via Customer: `Subscription.party` (Customer) -> `Member.customer`
2. Via Membership: `Membership.subscription` -> `Membership.member` -> `Member.chapter`

```python
def get_subscription_query_condition(user: str) -> str:
    # ... base checks ...
    return f"""
        (`tabSubscription`.`party_type` != 'Customer'
        OR EXISTS (SELECT 1 FROM `tabMember` m WHERE m.customer = `tabSubscription`.`party` AND ...)
        OR EXISTS (SELECT 1 FROM `tabMembership` ms JOIN `tabMember` m ON m.name = ms.member 
                   WHERE ms.subscription = `tabSubscription`.`name` AND ...))
    """
```

---

## 19. NestedSet for Hierarchies

Chapters use `lft`/`rgt` for tree structure:

```python
# Get descendants
frappe.db.sql_list(
    "SELECT name FROM `tabChapter` WHERE lft > %s AND rgt < %s",
    (chapter.lft, chapter.rgt),
)

# Get ancestors (ordered from immediate parent to root)
frappe.db.sql_list(
    "SELECT name FROM `tabChapter` WHERE lft < %s AND rgt > %s ORDER BY lft DESC",
    (chapter.lft, chapter.rgt),
)
```

---

## 20. Dynamic Links (Contact/Address)

Contacts and Addresses use `tabDynamic Link` table for polymorphic relationships:

- Fields: `parent`, `parenttype`, `link_doctype`, `link_name`
- **Native Frappe permission only checks**: Customer, Supplier, Company, Sales Partner
- To restrict by Member or other doctypes, must add custom `permission_query_conditions`

### Fetching Primary Contact for Customer

```python
def get_primary_contact_for_customer(customer: str):
    """Get the primary contact for a customer."""
    contact_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer,
            "parenttype": "Contact",
        },
        fields=["parent"],
        pluck="parent",
    )

    if not contact_names:
        return None

    # Check for primary contact
    primary_contact = frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names], "is_primary_contact": 1},
        ["name", "first_name", "last_name"],
        as_dict=True,
    )

    if primary_contact:
        return primary_contact

    # Fall back to first contact
    return frappe.db.get_value(
        "Contact",
        {"name": ["in", contact_names]},
        ["name", "first_name", "last_name"],
        as_dict=True,
    )
```

---

## 21. Translations

### File Location

`apps/{app}/{app}/translations/{lang}.csv`

### Format

```csv
"Source Text","Translated Text"
"Active","Aktiv"
"Member","Mitglied"
```

### Usage in Code

- Python: `_("text")` or `frappe._("text")`
- JavaScript: `__("text")`

### Alternative: Database Translations

Create records in `Translation` DocType:
- `language`: Language code (e.g., "de")
- `source_text`: Original English text
- `translated_text`: Translated text

---

## 22. Form UI Patterns (JavaScript)

### Form Indicators

```javascript
// Form header indicator
frm.page.set_indicator(__('Active'), 'green');

// Dashboard headline
frm.dashboard.set_headline('Payment Due', 'orange');
```

### List View Indicators

```javascript
frappe.listview_settings['Membership'] = {
    get_indicator: function(doc) {
        if (doc.subscription_status === 'Active') {
            return [__('Active'), 'green', 'subscription_status,=,Active'];
        }
        // ...
    }
};
```

### Syncing Data on Form Load

```python
class Membership(Document):
    def onload(self):
        """Sync subscription status on load."""
        self.sync_status_from_subscription()

    def sync_status_from_subscription(self):
        if self.subscription:
            status = frappe.db.get_value("Subscription", self.subscription, "status")
            if status and status != self.subscription_status:
                self.subscription_status = status
                self.db_set("subscription_status", status)
```

---

## 23. Caching Patterns

### Basic Caching

```python
def get_user_accessible_chapters(user: str) -> list[str]:
    cache_key = f"accessible_chapters:{user}"
    cached = frappe.cache.get_value(cache_key)
    if cached is not None:
        return cached
    
    # ... compute result ...
    
    frappe.cache.set_value(cache_key, result, expires_in_sec=300)
    return result
```

### Cache Clearing on Related Changes

```python
def clear_user_chapter_cache(doc, method=None):
    if doc.allow != "Chapter":
        return
    cache_key = f"accessible_chapters:{doc.user}"
    frappe.cache.delete_value(cache_key)
```

Hook in `hooks.py`:
```python
doc_events = {
    "User Permission": {
        "on_trash": "non_profit.non_profit.permissions.clear_user_chapter_cache",
        "on_update": "non_profit.non_profit.permissions.clear_user_chapter_cache",
    },
}
```

---

## 24. Subscription and Membership Patterns

### Relationship Flow

```
Member (customer) -> Customer
     |
     v
Membership (member) -> Member
     |
     v
Subscription (party=customer) -> Customer
     |
     v
Sales Invoice (customer) -> Customer
```

### Use db_set() for Linked Fields

Update linked fields without triggering hooks:

```python
member.db_set("subscription", sub.name)
self.db_set("subscription", sub.name)
```

### Membership Status Sync Pattern

```python
class Membership(Document):
    def onload(self):
        """Sync subscription status on load."""
        self.sync_status_from_subscription()

    def sync_status_from_subscription(self):
        if self.subscription:
            status = frappe.db.get_value("Subscription", self.subscription, "status")
            if status and status != self.subscription_status:
                self.subscription_status = status
                self.db_set("subscription_status", status)
```

---

## 25. Known Gotchas

### "Administrator" is Hardcoded

"Administrator" username is hardcoded in 67+ places in Frappe core for:
- Permission bypasses
- Impersonation feature
- 2FA skip logic
- Permission Manager access
- Custom Field protection

**Do not rename this user.**

### Impersonation Feature Inconsistency

The impersonation button has inconsistent checks:
- **Frontend** (`user.js`): Only checks `frappe.session.user === "Administrator"` (hardcoded string!)
- **Backend** (`user.py`): Properly checks `frappe.has_permission("User", "impersonate")`

If you renamed "Administrator" user, the impersonation button won't appear. The frontend check should be fixed to use permissions instead of hardcoded username.

### Date Fields and JavaScript

Never set text values to Date fields via JavaScript:

```javascript
// WRONG - causes "Invalid date format" error
frm.set_value('membership_expiry_date', 'Active');

// CORRECT - use dashboard headline or indicator instead
frm.dashboard.set_headline('Active', 'green');
```

### fetch_from Only Works on Form Load

JSON field definitions with `fetch_from` only populate when the form loads and the source field changes. They don't work when setting values programmatically.

### SQL Injection Prevention

Always escape user input in raw SQL:

```python
chapter_list = "', '".join([c.replace("'", "''") for c in accessible_chapters])
return f"`tabChapter`.`name` IN ('{chapter_list}')"
```

---

## 26. Non Profit App: Member and Membership Structure

### Entity Relationships

```
CUSTOMER (existing)
    |
    | (select existing)
    v
MEMBER
    - customer (mandatory)
    - first_name (fetched from Contact)
    - last_name (fetched from Contact)
    - subscription
    |
    | (required)
    v
MEMBERSHIP
    - member (mandatory)
    - membership_type
    - subscription (auto-created if auto_renew)
    |
    | (creates on submit)
    v
SUBSCRIPTION
    - party_type = "Customer"
    - party = (from Member.customer)
    |
    | (generates)
    v
SALES INVOICE
    - customer = (from Member.customer)
```

### Member Validation

```python
class Member(Document):
    def validate(self):
        if not self.customer:
            frappe.throw(_("Customer is required"))

        if self.email_id:
            self.validate_email_type(self.email_id)

        self.fetch_contact_details()
```

### Membership Validation

```python
class Membership(Document):
    def validate(self):
        if not self.member:
            frappe.throw(_("Member is required"))

        customer = frappe.db.get_value("Member", self.member, "customer")
        if not customer:
            frappe.throw(
                _("Member {0} does not have a Customer linked.").format(self.member)
            )
```

### Data Flow

1. User creates/selects **Customer** (must have Contact with first_name/last_name)
2. User creates **Member** with customer selected
3. Member auto-fetches first_name/last_name from Contact linked to Customer
4. User creates **Membership** linked to Member
5. On submit (if auto_renew), Membership creates **Subscription** with party=Member.customer
6. Subscription generates **Sales Invoices** automatically

---

## 27. Useful Commands

```bash
# Restart bench after code changes
bench restart

# Clear cache
bench --site [site] clear-cache

# Check Python syntax
python3 -m py_compile path/to/file.py

# Execute Python in Frappe context
bench --site <sitename> execute "module.path.function"

# Run specific test
bench --site [site] run-tests --doctype "DocType" --test "test_name"

# Open console
bench --site [site] console

# Reload doctype from JSON
bench --site [site] reload-doctype "DocType Name" --app my_app
``` 
