import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.database import get_db
from frappe.desk.page.setup_wizard.setup_wizard import make_records
from frappe.model import no_value_fields
from frappe.utils import cint

NON_PROFIT_DESK_ROLES = ("Non Profit Manager", "Non Profit Member")
PUBLIC_IDENTITY_INDEXES = (
	("Member", "email_id", "non_profit_member_email_id_index"),
	("Customer", "email_id", "non_profit_customer_email_id_index"),
	("Donor", "customer", "non_profit_donor_customer_index"),
)


def make_custom_records():
	records = [
		{"doctype": "Party Type", "party_type": "Member", "account_type": "Receivable"},
		{"doctype": "Party Type", "party_type": "Donor", "account_type": "Receivable"},
	]
	make_records(records)


def setup_non_profit():
	make_custom_records()
	make_custom_fields()
	from non_profit.non_profit.erpnext_loyalty import disable_test_loyalty_auto_opt_in

	disable_test_loyalty_auto_opt_in()

	has_domain = frappe.get_doc(
		{
			"doctype": "Has Domain",
			"parent": "Domain Settings",
			"parentfield": "active_domains",
			"parenttype": "Domain Settings",
			"domain": "Non Profit",
		}
	)
	has_domain.save()

	domain = frappe.get_doc("Domain", "Non Profit")
	domain.setup_domain()

	domain_settings = frappe.get_single("Domain Settings")
	domain_settings.append("active_domains", dict(domain=domain))
	frappe.clear_cache()
	ensure_non_profit_desk_roles()
	from non_profit.non_profit.fundraising_setup import ensure_good_connector_bank_integration
	from non_profit.non_profit.major_gifts import ensure_major_gift_workflow

	ensure_good_connector_bank_integration()
	ensure_major_gift_workflow()
	frappe.db.after_commit.add(ensure_public_identity_database_indexes)


def ensure_non_profit_desk_roles():
	for role_name in NON_PROFIT_DESK_ROLES:
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)

		changed = False
		if not role.desk_access:
			role.desk_access = 1
			changed = True
		if role.disabled:
			role.disabled = 0
			changed = True

		if changed:
			role.save(ignore_permissions=True)

	_ensure_role_users_are_system_users(NON_PROFIT_DESK_ROLES)


def _ensure_role_users_are_system_users(roles):
	user_names = frappe.get_all(
		"Has Role",
		filters={
			"parenttype": "User",
			"role": ["in", list(roles)],
		},
		pluck="parent",
		distinct=True,
	)
	for user_name in user_names:
		if user_name in {"Administrator", "Guest"}:
			continue
		if frappe.db.get_value("User", user_name, "user_type") == "System User":
			continue

		user = frappe.get_doc("User", user_name)
		user.user_type = "System User"
		user.save(ignore_permissions=True)
		frappe.clear_cache(user=user_name)


def before_uninstall():
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return
	frappe.db.set_value(
		"Workspace Sidebar",
		{"app": "non_profit"},
		"app",
		"",
		update_modified=False,
	)


data = {"on_setup": "non_profit.setup.setup_non_profit"}


def before_install() -> None:
	ensure_customer_email_search_index()


def before_migrate() -> None:
	ensure_customer_email_search_index()


def ensure_customer_email_search_index() -> None:
	if not frappe.db.exists("DocType", "Customer"):
		return
	field = frappe.get_meta("Customer").get_field("email_id")
	if not field:
		return
	property_setter_name = frappe.db.get_value(
		"Property Setter",
		{
			"doc_type": "Customer",
			"field_name": "email_id",
			"property": "search_index",
		},
		"name",
	)
	if property_setter_name:
		current = frappe.db.get_value(
			"Property Setter",
			property_setter_name,
			["value", "property_type", "is_system_generated", "module"],
			as_dict=True,
		)
		owned_by_non_profit = current and current.module == "Non Profit"
		if not owned_by_non_profit:
			if current and cint(current.value):
				frappe.clear_cache(doctype="Customer")
				return
			frappe.throw(
				frappe._(
					"Customer email indexing is disabled by an operator or another app. "
					"Enable search_index on Customer.email_id before installing or migrating Non Profit."
				),
				frappe.ValidationError,
			)
		updates = {
			fieldname: value
			for fieldname, value in {
				"value": "1",
				"property_type": "Check",
				"is_system_generated": 1,
				"module": "Non Profit",
			}.items()
			if current and current.get(fieldname) != value
		}
		if updates:
			frappe.db.set_value(
				"Property Setter",
				property_setter_name,
				updates,
				update_modified=False,
			)
			frappe.clear_cache(doctype="Customer")
		return
	if cint(field.search_index):
		return
	property_setter = make_property_setter("Customer", "email_id", "search_index", 1, "Check")
	property_setter.db_set("module", "Non Profit", update_modified=False)


def ensure_public_identity_database_indexes() -> None:
	"""Create missing physical indexes on an isolated database connection."""
	database = _new_database_connection()
	indexes_added = False
	try:
		for doctype, fieldname, index_name in PUBLIC_IDENTITY_INDEXES:
			if not database.table_exists(doctype, cached=False):
				continue
			table_name = f"tab{doctype}"
			columns = {
				row.get("name") if hasattr(row, "get") else row[0]
				for row in database.get_table_columns_description(table_name)
			}
			if fieldname not in columns:
				continue
			if _has_equivalent_column_index(database, table_name, fieldname, index_name):
				continue
			_add_public_identity_database_index(database, doctype, fieldname, index_name)
			indexes_added = True
		if indexes_added:
			# This dedicated connection has no request/migrate transaction callbacks.
			database.commit()  # nosemgrep: frappe-manual-commit
	except Exception:
		database.rollback()
		raise
	finally:
		database.close()


def _new_database_connection():
	configuration = frappe.conf
	return get_db(
		socket=configuration.db_socket,
		host=configuration.db_host,
		port=configuration.db_port,
		user=configuration.db_user or configuration.db_name,
		password=configuration.db_password,
		cur_db_name=configuration.db_name,
	)


def _add_public_identity_database_index(database, doctype: str, fieldname: str, index_name: str) -> None:
	table_name = f"tab{doctype}"
	if database.db_type == "postgres":
		query = (
			f'CREATE INDEX IF NOT EXISTS "{index_name}" '
			f'ON "{database.db_schema}"."{table_name}" ("{fieldname}")'
		)
	elif database.db_type == "sqlite":
		query = f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ("{fieldname}")'
	else:
		query = f"ALTER TABLE `{table_name}` ADD INDEX IF NOT EXISTS `{index_name}` (`{fieldname}`)"
	# Identifiers come exclusively from PUBLIC_IDENTITY_INDEXES above.
	database.sql(query)  # nosemgrep: frappe-sql-format-injection


def _has_equivalent_column_index(database, table_name: str, fieldname: str, index_name: str) -> bool:
	if get_column_index := getattr(database, "get_column_index", None):
		index = get_column_index(table_name, fieldname, unique=False) or get_column_index(
			table_name, fieldname, unique=True
		)
		return bool(index and not (database.db_type == "sqlite" and index.get("partial")))
	if database.db_type == "postgres":
		return bool(
			database.sql(
				"""
				SELECT 1
				FROM pg_index AS index_definition
				JOIN pg_class AS table_definition
					ON table_definition.oid = index_definition.indrelid
				JOIN pg_namespace AS table_namespace
					ON table_namespace.oid = table_definition.relnamespace
				JOIN pg_attribute AS column_definition
					ON column_definition.attrelid = table_definition.oid
					AND column_definition.attnum = index_definition.indkey[0]
				WHERE table_namespace.nspname = %s
					AND table_definition.relname = %s
					AND column_definition.attname = %s
					AND index_definition.indisvalid = TRUE
					AND index_definition.indpred IS NULL
					AND index_definition.indnkeyatts = 1
				LIMIT 1
				""",
				(database.db_schema, table_name, fieldname),
			)
		)
	return any(
		database.has_index(table_name, existing_name)
		for existing_name in (fieldname, f"{fieldname}_index", index_name)
	)


def after_migrate():
	make_custom_fields()
	from non_profit.non_profit.fundraising_setup import ensure_fundraising_fixtures

	ensure_fundraising_fixtures()
	frappe.db.after_commit.add(ensure_public_identity_database_indexes)


def after_app_install(app_name: str) -> None:
	if app_name != "workflow_visualizer":
		return

	from non_profit.non_profit.major_gifts import ensure_major_gift_workflow

	ensure_major_gift_workflow()


def make_custom_fields(update=True):
	custom_fields = get_custom_fields()
	if custom_fields:
		create_custom_fields(custom_fields, update=update)
		for doctype, fields in custom_fields.items():
			if any(
				field["fieldtype"] not in no_value_fields
				and not frappe.db.has_column(doctype, field["fieldname"])
				for field in fields
			):
				frappe.clear_cache(doctype=doctype)
				frappe.db.updatedb(doctype)


def get_custom_fields():
	person_language_module = (
		"Good Connector" if "good_connector" in frappe.get_installed_apps() else "Non Profit"
	)
	custom_fields = {
		"Contact": [
			{
				"fieldname": "title",
				"label": "Title",
				"fieldtype": "Data",
				"insert_after": "salutation",
			},
			{
				"fieldname": "preferred_language",
				"label": "Preferred Language",
				"fieldtype": "Link",
				"options": "Language",
				"insert_after": "salutation",
				"module": person_language_module,
			},
			{
				"fieldname": "npo_identity_kind",
				"label": "NPO Identity Kind",
				"fieldtype": "Select",
				"options": "\nPerson\nGeneric Endpoint",
				"insert_after": "preferred_language",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Customer": [
			{
				"fieldname": "household",
				"label": "Household",
				"fieldtype": "Link",
				"options": "Household",
				"insert_after": "territory",
			},
			{
				"fieldname": "npo_subject_type",
				"label": "NPO Subject Type",
				"fieldtype": "Select",
				"options": "\nPerson\nOrganization\nHousehold",
				"insert_after": "household",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "npo_contact",
				"label": "NPO Contact",
				"fieldtype": "Link",
				"options": "Contact",
				"insert_after": "npo_subject_type",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"search_index": 1,
			},
			{
				"fieldname": "npo_organization",
				"label": "NPO Organization",
				"fieldtype": "Link",
				"options": "NPO Organization",
				"insert_after": "npo_contact",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"search_index": 1,
			},
			{
				"fieldname": "npo_household",
				"label": "NPO Household",
				"fieldtype": "Link",
				"options": "Household",
				"insert_after": "npo_organization",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"search_index": 1,
			},
		],
		"Supplier": [
			{
				"fieldname": "npo_subject_type",
				"label": "NPO Subject Type",
				"fieldtype": "Select",
				"options": "\nPerson\nOrganization",
				"insert_after": "supplier_name",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "npo_contact",
				"label": "NPO Contact",
				"fieldtype": "Link",
				"options": "Contact",
				"insert_after": "npo_subject_type",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"search_index": 1,
			},
			{
				"fieldname": "npo_organization",
				"label": "NPO Organization",
				"fieldtype": "Link",
				"options": "NPO Organization",
				"insert_after": "npo_contact",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"search_index": 1,
			},
		],
		"Task": [
			{
				"fieldname": "donor",
				"label": "Donor",
				"fieldtype": "Link",
				"options": "Donor",
				"insert_after": "project",
				"no_copy": 1,
			},
			{
				"fieldname": "major_gift",
				"label": "Major Gift",
				"fieldtype": "Link",
				"options": "Major Gift",
				"insert_after": "donor",
				"no_copy": 1,
			},
		],
	}
	if frappe.db.exists("DocType", "Donation"):
		custom_fields["Donation"] = get_donation_payment_custom_fields()
	for fields in custom_fields.values():
		for field in fields:
			field.setdefault("module", "Non Profit")
	return custom_fields


def get_donation_payment_custom_fields():
	"""Donation mirrors of the Sales Invoice fields that ERPNext's generic
	Payment Entry reference-details fallback reads.

	ERPNext computes outstanding as ``grand_total - advance_paid`` for any
	reference doctype it does not special-case. Maintaining these two fields
	keeps Donation references correct no matter which app wins the
	``override_doctype_class`` resolution for Payment Entry (see
	``non_profit/non_profit/custom_doctype/payment_entry.py``).
	"""
	return [
		{
			"fieldname": "grand_total",
			"label": "Grand Total",
			"fieldtype": "Currency",
			"insert_after": "amount",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "advance_paid",
			"label": "Advance Paid",
			"fieldtype": "Currency",
			"insert_after": "grand_total",
			"read_only": 1,
			"no_copy": 1,
		},
	]
