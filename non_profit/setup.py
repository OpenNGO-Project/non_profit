import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.page.setup_wizard.setup_wizard import make_records
from frappe.model import no_value_fields

NON_PROFIT_DESK_ROLES = ("Non Profit Manager", "Non Profit Member")


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

	ensure_good_connector_bank_integration()


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


def after_migrate():
	make_custom_fields()
	from non_profit.non_profit.fundraising_setup import ensure_fundraising_fixtures

	ensure_fundraising_fixtures()


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
				"insert_after": "title",
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
