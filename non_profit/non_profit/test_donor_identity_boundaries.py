from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from hashlib import sha256
from inspect import getsource
from time import sleep
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from non_profit import hooks, setup
from non_profit.non_profit import donor_identity, legacy_payments
from non_profit.non_profit.doctype.donation import donation as donation_module


class TestDonorIdentityBoundaries(UnitTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.original_user = frappe.session.user
		self.enterContext(patch.object(donor_identity, "current_identity_read", return_value=nullcontext()))

	def tearDown(self) -> None:
		frappe.session.user = self.original_user
		super().tearDown()

	def website_donation(self, email: str) -> donation_module.Donation:
		frappe.session.user = email
		return donation_module.Donation({"doctype": "Donation", "donor_type": "_Test Donor", "__islocal": 1})

	def test_website_user_donor_resolution_rejects_ambiguous_email(self) -> None:
		email = "ambiguous-website-user@example.org"
		donation = self.website_donation(email)
		with (
			patch.object(donation_module.frappe.db, "get_value", return_value="Website Donor"),
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=(["DONOR-1", "DONOR-2"], []),
			),
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
		):
			donation.create_donor_for_website_user()

	def test_website_user_donor_resolution_rejects_multiple_customers_without_pii_logging(self) -> None:
		email = "ambiguous-customers@example.org"
		donation = self.website_donation(email)
		with (
			patch.object(donation_module.frappe.db, "get_value", return_value="Website Donor"),
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=([], ["CUSTOMER-1", "CUSTOMER-2"]),
			),
			patch.object(donor_identity.frappe, "logger") as logger,
			patch.object(donor_identity.frappe, "log_error") as log_error,
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
		):
			donation.create_donor_for_website_user()

		logged = str(logger.return_value.warning.call_args)
		self.assertNotIn(email, logged)
		self.assertIn(sha256(email.encode()).hexdigest(), logged)
		log_error.assert_not_called()

	def test_website_user_new_identity_uses_reject_policy_and_sets_donor(self) -> None:
		email = "new-website-user@example.org"
		donation = self.website_donation(email)
		resolved_donor = frappe._dict(name="DONOR-NEW")
		with (
			patch.object(donation_module.frappe.db, "get_value", return_value="New Website Donor"),
			patch.object(
				donor_identity,
				"resolve_donor_customer_identity",
				return_value=(resolved_donor, "CUSTOMER-NEW"),
			) as resolve_identity,
		):
			donation.create_donor_for_website_user()

		self.assertEqual(donation.donor, resolved_donor.name)
		resolve_identity.assert_called_once_with(
			donor_name="New Website Donor",
			email=email,
			donor_type="_Test Donor",
			ambiguous_email_policy="reject",
		)

	def test_legacy_gateway_donor_resolution_rejects_ambiguous_email(self) -> None:
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=(["DONOR-1", "DONOR-2"], []),
			),
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
		):
			legacy_payments.get_gateway_donor("ambiguous-gateway@example.org")

	def test_legacy_gateway_rejects_unproven_donor_customer_pair(self) -> None:
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=(["DONOR-1"], ["CUSTOMER-1"]),
			),
			patch.object(donor_identity, "donor_customer_share_identity", return_value=False),
			self.assertRaisesRegex(frappe.ValidationError, "could not process your donation"),
		):
			legacy_payments.get_gateway_donor("unproven-gateway@example.org")

	def test_legacy_gateway_returns_unique_existing_donor(self) -> None:
		expected = frappe._dict(name="DONOR-1")
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=([expected.name], []),
			),
			patch.object(donor_identity.frappe, "get_doc", return_value=expected) as get_doc,
		):
			self.assertIs(legacy_payments.get_gateway_donor("unique-gateway@example.org"), expected)

		get_doc.assert_called_once_with("Donor", expected.name, for_update=True)

	def test_legacy_gateway_returns_none_without_existing_identity(self) -> None:
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(donor_identity, "find_donor_customer_candidates", return_value=([], [])),
			patch.object(donor_identity.frappe, "get_doc") as get_doc,
		):
			self.assertIsNone(legacy_payments.get_gateway_donor("missing-gateway@example.org"))

		get_doc.assert_not_called()

	def test_candidate_drift_is_retryable_and_safe_for_public_validation(self) -> None:
		email = "candidate-drift@example.org"
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				side_effect=[(["DONOR-1"], []), (["DONOR-1", "DONOR-2"], [])],
			),
			self.assertRaises(donor_identity.IdentityCandidateDriftError) as raised,
		):
			donor_identity.get_unambiguous_donor_by_email(email)

		self.assertIsInstance(raised.exception, frappe.QueryDeadlockError)
		self.assertIsInstance(raised.exception, frappe.ValidationError)
		self.assertNotIn(email, str(raised.exception))
		self.assertIn("retry", str(raised.exception).lower())

	def test_current_identity_read_ends_before_handlers_and_identity_writes(self) -> None:
		state = {"active": False}
		donor = frappe._dict(name="DONOR-1", customer="CUSTOMER-1")

		@contextmanager
		def current_read():
			state["active"] = True
			try:
				yield
			finally:
				state["active"] = False

		def candidates(_email: str, *, for_update: bool = False):
			self.assertTrue(state["active"])
			return [donor.name], [donor.customer]

		def get_doc(*_args, **_kwargs):
			self.assertTrue(state["active"])
			return donor

		def existing_handler(_donor):
			self.assertFalse(state["active"])

		def get_or_create(_donor, **_kwargs):
			self.assertFalse(state["active"])
			return donor.customer

		with (
			patch.object(donor_identity, "current_identity_read", side_effect=current_read),
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(donor_identity, "find_donor_customer_candidates", side_effect=candidates),
			patch.object(donor_identity, "donor_customer_share_identity", return_value=True),
			patch.object(donor_identity.frappe.db, "get_value", return_value=donor.customer),
			patch.object(donor_identity.frappe, "get_doc", side_effect=get_doc),
			patch.object(donor_identity, "get_or_create_customer_for_donor", side_effect=get_or_create),
		):
			resolved_donor, customer = donor_identity.resolve_donor_customer_identity(
				donor_name="Existing Donor",
				email="existing-donor@example.org",
				donor_type="Individual",
				ambiguous_email_policy="reject",
				existing_donor_handler=existing_handler,
			)

		self.assertIs(resolved_donor, donor)
		self.assertEqual(customer, donor.customer)

	def test_resolution_retries_when_current_donor_customer_link_differs_from_snapshot(self) -> None:
		donor = frappe._dict(name="DONOR-1", customer="CUSTOMER-CURRENT")
		with (
			patch.object(donor_identity, "acquire_public_email_identity_lock"),
			patch.object(
				donor_identity,
				"find_donor_customer_candidates",
				return_value=([donor.name], []),
			),
			patch.object(donor_identity.frappe.db, "get_value", return_value=None),
			patch.object(donor_identity.frappe, "get_doc", return_value=donor),
			patch.object(donor_identity, "get_or_create_customer_for_donor") as get_or_create,
			self.assertRaises(donor_identity.IdentityCandidateDriftError),
		):
			donor_identity.resolve_donor_customer_identity(
				donor_name="Existing Donor",
				email="linked-customer-drift@example.org",
				donor_type="Individual",
			)

		get_or_create.assert_not_called()

	def test_public_identity_index_metadata_runs_before_install_and_migrate(self) -> None:
		self.assertEqual(hooks.before_install, "non_profit.setup.before_install")
		self.assertEqual(hooks.before_migrate, "non_profit.setup.before_migrate")
		for lifecycle_function in (setup.setup_non_profit, setup.after_migrate):
			source = getsource(lifecycle_function)
			self.assertIn("frappe.db.after_commit.add(ensure_public_identity_database_indexes)", source)
			self.assertNotIn("ensure_public_identity_database_indexes()", source)
		self.assertNotIn("frappe.db.commit", getsource(setup.ensure_public_identity_database_indexes))

	def test_public_identity_fields_declare_persistent_indexes(self) -> None:
		self.assertTrue(frappe.get_meta("Member").get_field("email_id").search_index)
		self.assertTrue(frappe.get_meta("Customer").get_field("email_id").search_index)
		self.assertTrue(frappe.get_meta("Donor").get_field("customer").search_index)
		get_column_index = getattr(frappe.db, "get_column_index", None)
		if get_column_index:
			self.assertTrue(get_column_index("tabMember", "email_id", unique=False))
			self.assertTrue(get_column_index("tabCustomer", "email_id", unique=False))
			self.assertTrue(get_column_index("tabDonor", "customer", unique=False))

	def test_public_identity_index_setup_skips_equivalent_indexes(self) -> None:
		database = MagicMock()
		database.table_exists.return_value = True
		database.get_table_columns_description.return_value = [
			frappe._dict(name=fieldname) for _doctype, fieldname, _index_name in setup.PUBLIC_IDENTITY_INDEXES
		]
		with (
			patch.object(setup, "_new_database_connection", return_value=database),
			patch.object(setup, "_has_equivalent_column_index", return_value=True),
			patch.object(setup, "_add_public_identity_database_index") as add_index,
		):
			setup.ensure_public_identity_database_indexes()

		add_index.assert_not_called()
		database.has_column.assert_not_called()
		self.assertEqual(database.get_table_columns_description.call_count, 3)
		database.commit.assert_not_called()
		database.close.assert_called_once_with()

	def test_public_identity_index_setup_detects_postgres_equivalent_indexes(self) -> None:
		database = MagicMock(db_type="postgres", db_schema="public")
		database.get_column_index = None
		database.sql.return_value = [[1]]
		with (
			patch.object(setup, "_add_public_identity_database_index") as add_index,
		):
			for doctype, fieldname, index_name in setup.PUBLIC_IDENTITY_INDEXES:
				self.assertTrue(
					setup._has_equivalent_column_index(database, f"tab{doctype}", fieldname, index_name)
				)

		self.assertEqual(database.sql.call_count, 3)
		self.assertIn("index_definition.indpred IS NULL", database.sql.call_args.args[0])
		add_index.assert_not_called()

	def test_partial_sqlite_index_does_not_suppress_full_index_creation(self) -> None:
		database = MagicMock(db_type="sqlite")
		database.get_column_index.return_value = frappe._dict(partial=1)
		self.assertFalse(
			setup._has_equivalent_column_index(
				database,
				"tabCustomer",
				"email_id",
				"non_profit_customer_email_id_index",
			)
		)

	def test_public_identity_index_setup_uses_isolated_connection_without_metadata_takeover(self) -> None:
		database = MagicMock()
		database.table_exists.return_value = True
		database.get_table_columns_description.return_value = [
			frappe._dict(name=fieldname) for _doctype, fieldname, _index_name in setup.PUBLIC_IDENTITY_INDEXES
		]
		with (
			patch.object(setup, "_new_database_connection", return_value=database),
			patch.object(setup, "_has_equivalent_column_index", return_value=False),
			patch.object(setup, "_add_public_identity_database_index") as add_index,
			patch.object(setup.frappe.db, "commit") as request_commit,
			patch.object(setup, "make_property_setter") as make_property_setter,
		):
			setup.ensure_public_identity_database_indexes()

		self.assertEqual(add_index.call_count, 3)
		database.has_column.assert_not_called()
		self.assertEqual(database.get_table_columns_description.call_count, 3)
		database.commit.assert_called_once_with()
		database.close.assert_called_once_with()
		request_commit.assert_not_called()
		make_property_setter.assert_not_called()

	def test_public_identity_index_ddl_is_portable_and_table_scoped(self) -> None:
		for database_type, expected in (
			("mariadb", "ALTER TABLE `tabCustomer` ADD INDEX IF NOT EXISTS"),
			("postgres", 'ON "public"."tabCustomer"'),
			("sqlite", 'ON "tabCustomer"'),
		):
			database = MagicMock(db_type=database_type, db_schema="public")
			setup._add_public_identity_database_index(
				database,
				"Customer",
				"email_id",
				"non_profit_customer_email_id_index",
			)

			query = database.sql.call_args.args[0]
			self.assertIn(expected, query)
			self.assertIn("non_profit_customer_email_id_index", query)
			self.assertIn("email_id", query)

	def test_customer_email_property_setter_is_owned_by_non_profit(self) -> None:
		field = frappe._dict(search_index=0)
		meta = MagicMock()
		meta.get_field.return_value = field
		property_setter = MagicMock()
		with (
			patch.object(setup.frappe.db, "exists", return_value=True),
			patch.object(setup.frappe.db, "get_value", return_value=None),
			patch.object(setup.frappe, "get_meta", return_value=meta),
			patch.object(setup, "make_property_setter", return_value=property_setter),
		):
			setup.ensure_customer_email_search_index()

		property_setter.db_set.assert_called_once_with("module", "Non Profit", update_modified=False)

	def test_customer_email_property_setter_preserves_compatible_foreign_metadata(self) -> None:
		meta = MagicMock()
		meta.get_field.return_value = frappe._dict(search_index=1)
		current = frappe._dict(
			value="1",
			property_type="Check",
			is_system_generated=0,
			module="Foreign App",
		)
		with (
			patch.object(setup.frappe.db, "exists", return_value=True),
			patch.object(
				setup.frappe.db,
				"get_value",
				side_effect=["Customer-email_id-search_index", current],
			) as get_value,
			patch.object(setup.frappe.db, "set_value") as set_value,
			patch.object(setup, "make_property_setter") as make_property_setter,
			patch.object(setup.frappe, "get_meta", return_value=meta),
			patch.object(setup.frappe, "clear_cache") as clear_cache,
		):
			setup.ensure_customer_email_search_index()

		lookup_filters = get_value.call_args_list[0].args[1]
		self.assertNotIn("value", lookup_filters)
		self.assertNotIn("is_system_generated", lookup_filters)
		set_value.assert_not_called()
		make_property_setter.assert_not_called()
		clear_cache.assert_called_once_with(doctype="Customer")

	def test_customer_email_property_setter_rejects_foreign_disable_without_mutation(self) -> None:
		meta = MagicMock()
		meta.get_field.return_value = frappe._dict(search_index=0)
		current = frappe._dict(
			value="0",
			property_type="Check",
			is_system_generated=0,
			module="Foreign App",
		)
		with (
			patch.object(setup.frappe.db, "exists", return_value=True),
			patch.object(
				setup.frappe.db,
				"get_value",
				side_effect=["Customer-email_id-search_index", current],
			),
			patch.object(setup.frappe.db, "set_value") as set_value,
			patch.object(setup, "make_property_setter") as make_property_setter,
			patch.object(setup.frappe, "get_meta", return_value=meta),
			self.assertRaisesRegex(frappe.ValidationError, "indexing is disabled"),
		):
			setup.ensure_customer_email_search_index()

		set_value.assert_not_called()
		make_property_setter.assert_not_called()

	def test_customer_email_property_setter_preserves_compatible_unowned_system_metadata(self) -> None:
		meta = MagicMock()
		meta.get_field.return_value = frappe._dict(search_index=1)
		current = frappe._dict(
			value="1",
			property_type="Check",
			is_system_generated=1,
			module=None,
		)
		with (
			patch.object(setup.frappe.db, "exists", return_value=True),
			patch.object(
				setup.frappe.db,
				"get_value",
				side_effect=["Customer-email_id-search_index", current],
			),
			patch.object(setup.frappe.db, "set_value") as set_value,
			patch.object(setup, "make_property_setter") as make_property_setter,
			patch.object(setup.frappe, "get_meta", return_value=meta),
			patch.object(setup.frappe, "clear_cache") as clear_cache,
		):
			setup.ensure_customer_email_search_index()

		set_value.assert_not_called()
		make_property_setter.assert_not_called()
		clear_cache.assert_called_once_with(doctype="Customer")

	def test_customer_email_property_setter_rejects_unowned_system_disable_without_mutation(self) -> None:
		meta = MagicMock()
		meta.get_field.return_value = frappe._dict(search_index=0)
		current = frappe._dict(
			value="0",
			property_type="Check",
			is_system_generated=1,
			module=None,
		)
		with (
			patch.object(setup.frappe.db, "exists", return_value=True),
			patch.object(
				setup.frappe.db,
				"get_value",
				side_effect=["Customer-email_id-search_index", current],
			),
			patch.object(setup.frappe.db, "set_value") as set_value,
			patch.object(setup, "make_property_setter") as make_property_setter,
			patch.object(setup.frappe, "get_meta", return_value=meta),
			self.assertRaisesRegex(frappe.ValidationError, "indexing is disabled"),
		):
			setup.ensure_customer_email_search_index()

		set_value.assert_not_called()
		make_property_setter.assert_not_called()


class TestDonorIdentityCurrentReads(IntegrationTestCase):
	def test_gateway_lookup_current_locks_the_selected_donor_document(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The stale-snapshot regression targets MariaDB/InnoDB")

		token = frappe.generate_hash(length=8)
		email = f"identity-field-snapshot-{token}@example.org"
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
		donor_type = frappe.db.get_value("Donor Type", {}, "name", order_by="name asc")
		with ThreadPoolExecutor(max_workers=1) as executor:
			donor_name, customer_name = executor.submit(
				_create_committed_donor_identity,
				frappe.local.site,
				email,
				customer_group,
				territory,
				donor_type,
			).result(timeout=30)
		try:
			frappe.db.rollback()
			original_label = frappe.db.get_value("Donor", donor_name, "donor_name")
			updated_label = f"Updated Identity {token}"
			with ThreadPoolExecutor(max_workers=1) as executor:
				executor.submit(
					_update_committed_donor_name,
					frappe.local.site,
					donor_name,
					updated_label,
				).result(timeout=30)
			self.assertNotEqual(original_label, updated_label)
			resolved = legacy_payments.get_gateway_donor(email)
			self.assertEqual(resolved.donor_name, updated_label)
		finally:
			frappe.db.rollback()
			_cleanup_committed_identity(
				frappe.local.site,
				donor_names=(donor_name,),
				customer_names=(customer_name,),
			)

	def test_gateway_lookup_sees_identity_committed_after_transaction_snapshot(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The stale-snapshot regression targets MariaDB/InnoDB")
		snapshot_isolation = frappe.db.sql("SELECT @@SESSION.innodb_snapshot_isolation")[0][0]
		if str(snapshot_isolation).upper() not in ("1", "ON"):
			self.skipTest("MariaDB snapshot isolation is not enabled")

		token = frappe.generate_hash(length=8)
		email = f"identity-snapshot-{token}@example.org"
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
		donor_type = frappe.db.get_value("Donor Type", {}, "name", order_by="name asc")
		self.assertTrue(customer_group)
		self.assertTrue(territory)
		self.assertTrue(donor_type)

		# Establish the repeatable-read snapshot before another transaction commits
		# the identity that the serialized lookup must still observe.
		self.assertEqual(donor_identity.find_donor_customer_candidates(email), ([], []))
		with ThreadPoolExecutor(max_workers=1) as executor:
			donor_name, customer_name = executor.submit(
				_create_committed_donor_identity,
				frappe.local.site,
				email,
				customer_group,
				territory,
				donor_type,
			).result(timeout=30)

		try:
			with self.assertRaises(frappe.QueryDeadlockError):
				legacy_payments.get_gateway_donor(email)
			frappe.db.rollback()
			resolved = legacy_payments.get_gateway_donor(email)
			self.assertEqual(resolved.name, donor_name)
		finally:
			frappe.db.rollback()
			_cleanup_committed_identity(
				frappe.local.site,
				donor_names=(donor_name,),
				customer_names=(customer_name,),
			)

	def test_resolution_retries_before_stale_donor_customer_link_can_be_overwritten(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The stale-snapshot regression targets MariaDB/InnoDB")
		snapshot_isolation = frappe.db.sql("SELECT @@SESSION.innodb_snapshot_isolation")[0][0]
		if str(snapshot_isolation).upper() not in ("1", "ON"):
			self.skipTest("MariaDB snapshot isolation is not enabled")

		token = frappe.generate_hash(length=8)
		email = f"identity-customer-link-drift-{token}@example.org"
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
		donor_type = frappe.db.get_value("Donor Type", {}, "name", order_by="name asc")
		self.assertTrue(customer_group)
		self.assertTrue(territory)
		self.assertTrue(donor_type)

		with ThreadPoolExecutor(max_workers=1) as executor:
			(
				donor_name,
				email_customer,
				contact_name,
				contact_email_names,
			) = executor.submit(
				_create_committed_donor_link_drift_fixture,
				frappe.local.site,
				email,
				customer_group,
				territory,
				donor_type,
			).result(timeout=30)

		concurrently_linked_customer = None
		concurrent_contact_names = ()
		concurrent_contact_email_names = ()
		concurrent_current_candidates = None
		try:
			frappe.db.rollback()
			self.assertEqual(
				donor_identity.find_donor_customer_candidates(email),
				([donor_name], [email_customer]),
			)
			self.assertIsNone(frappe.db.get_value("Donor", donor_name, "customer"))

			with ThreadPoolExecutor(max_workers=1) as executor:
				(
					concurrently_linked_customer,
					concurrent_contact_names,
					concurrent_contact_email_names,
					concurrent_current_candidates,
				) = executor.submit(
					_create_and_link_committed_donor_customer,
					frappe.local.site,
					donor_name,
					email,
					customer_group,
					territory,
				).result(timeout=30)
			self.assertEqual(concurrent_current_candidates, ([donor_name], [email_customer]))

			with self.assertRaises(donor_identity.IdentityCandidateDriftError):
				donor_identity.resolve_donor_customer_identity(
					donor_name="Stale Snapshot Donor",
					email=email,
					donor_type=donor_type,
					ambiguous_email_policy="latest",
				)

			frappe.db.rollback()
			self.assertEqual(
				frappe.db.get_value("Donor", donor_name, "customer"),
				concurrently_linked_customer,
			)
		finally:
			frappe.db.rollback()
			_cleanup_committed_identity(
				frappe.local.site,
				donor_names=(donor_name,),
				customer_names=(
					email_customer,
					*((concurrently_linked_customer,) if concurrently_linked_customer else ()),
				),
				contact_names=(contact_name, *concurrent_contact_names),
				contact_email_names=(*contact_email_names, *concurrent_contact_email_names),
			)


def _create_committed_donor_identity(
	site: str,
	email: str,
	customer_group: str,
	territory: str,
	donor_type: str,
) -> tuple[str, str]:
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Identity Snapshot {frappe.generate_hash(length=8)}",
				"customer_type": "Individual",
				"customer_group": customer_group,
				"territory": territory,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", customer.name, "email_id", email, update_modified=False)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Identity Snapshot Donor",
				"donor_type": donor_type,
				"customer": customer.name,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		return donor.name, customer.name
	finally:
		frappe.destroy()


def _create_committed_donor_link_drift_fixture(
	site: str,
	email: str,
	customer_group: str,
	territory: str,
	donor_type: str,
) -> tuple[str, str, str, tuple[str, ...]]:
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		email_customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Email Candidate {frappe.generate_hash(length=8)}",
				"customer_type": "Individual",
				"customer_group": customer_group,
				"territory": territory,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", email_customer.name, "email_id", email, update_modified=False)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Identity Link Drift",
			}
		)
		contact.add_email(email, is_primary=True)
		contact.insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": "Identity Link Drift Donor",
				"donor_type": donor_type,
				"contact": contact.name,
			}
		).insert(ignore_permissions=True)
		contact_email_names = tuple(row.name for row in contact.email_ids)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		return (
			donor.name,
			email_customer.name,
			contact.name,
			contact_email_names,
		)
	finally:
		frappe.destroy()


def _update_committed_donor_name(site: str, donor_name: str, donor_label: str) -> None:
	frappe.init(site=site)
	frappe.connect()
	try:
		frappe.db.set_value("Donor", donor_name, "donor_name", donor_label, update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
	finally:
		frappe.destroy()


def _create_and_link_committed_donor_customer(
	site: str,
	donor_name: str,
	email: str,
	customer_group: str,
	territory: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[list[str], list[str]]]:
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Concurrent Link {frappe.generate_hash(length=8)}",
				"customer_type": "Individual",
				"customer_group": customer_group,
				"territory": territory,
			}
		).insert(ignore_permissions=True)
		contact_names = tuple(
			frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Contact",
					"link_doctype": "Customer",
					"link_name": customer.name,
				},
				pluck="parent",
				order_by="parent asc",
			)
		)
		contact_email_names = (
			tuple(
				frappe.get_all(
					"Contact Email",
					filters={"parent": ["in", list(contact_names)]},
					pluck="name",
					order_by="name asc",
				)
			)
			if contact_names
			else ()
		)
		frappe.db.set_value("Donor", donor_name, "customer", customer.name, update_modified=False)
		current_candidates = donor_identity.find_donor_customer_candidates(email)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		return customer.name, contact_names, contact_email_names, current_candidates
	finally:
		frappe.destroy()


def _cleanup_committed_identity(
	site: str,
	*,
	donor_names: tuple[str, ...],
	customer_names: tuple[str, ...],
	contact_names: tuple[str, ...] = (),
	contact_email_names: tuple[str, ...] = (),
) -> None:
	with ThreadPoolExecutor(max_workers=1) as executor:
		executor.submit(
			_cleanup_committed_identity_connection,
			site,
			donor_names,
			customer_names,
			contact_names,
			contact_email_names,
		).result(timeout=30)


def _cleanup_committed_identity_connection(
	site: str,
	donor_names: tuple[str, ...],
	customer_names: tuple[str, ...],
	contact_names: tuple[str, ...],
	contact_email_names: tuple[str, ...],
) -> None:
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		for attempt in range(5):
			try:
				for donor_name in donor_names:
					if frappe.db.exists("Donor", donor_name):
						frappe.delete_doc("Donor", donor_name, force=True, ignore_permissions=True)
				for customer_name in customer_names:
					if frappe.db.exists("Customer", customer_name):
						frappe.delete_doc("Customer", customer_name, force=True, ignore_permissions=True)
				for contact_name in contact_names:
					if frappe.db.exists("Contact", contact_name):
						frappe.delete_doc("Contact", contact_name, force=True, ignore_permissions=True)
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
				remaining_masters = any(
					frappe.db.exists(doctype, name)
					for doctype, names in (
						("Donor", donor_names),
						("Customer", customer_names),
						("Contact", contact_names),
					)
					for name in names
				)
				remaining_contact_children = bool(
					contact_email_names
					and frappe.db.exists("Contact Email", {"name": ["in", list(contact_email_names)]})
				)
				remaining_contact_links = bool(
					contact_names
					and frappe.db.exists(
						"Dynamic Link",
						{"parenttype": "Contact", "parent": ["in", list(contact_names)]},
					)
				)
				if remaining_masters or remaining_contact_children or remaining_contact_links:
					raise AssertionError("Committed donor identity cleanup was incomplete")
				return
			except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):  # fmt: skip
				frappe.db.rollback()
				if attempt == 4:
					raise
				sleep(0.1 * (attempt + 1))
	finally:
		try:
			frappe.db.rollback()
		finally:
			frappe.destroy()
