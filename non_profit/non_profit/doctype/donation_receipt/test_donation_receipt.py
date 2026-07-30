from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import FrappeTestCase


class TestDonationReceipt(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_receipt_can_be_saved_before_donations_are_added(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
			}
		).insert(ignore_permissions=True)

		self.assertTrue(receipt.name)
		self.assertFalse(receipt.donations)
		self.assertEqual(receipt.total_amount, 0)

	def test_selected_year_helper_returns_unreceipted_paid_donations(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			get_donations_for_selected_year,
		)

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=42)

		result = get_donations_for_selected_year(fiscal_year=fiscal_year, donor=donor.name)

		donation_names = [row["donation"] for row in result["donations"]]
		self.assertIn(donation.name, donation_names)
		row = next(row for row in result["donations"] if row["donation"] == donation.name)
		self.assertEqual(row["amount"], 42)

	def test_receipt_total_is_computed_from_donation_rows(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=55)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(receipt.total_amount, 55)
		self.assertEqual(receipt.donations[0].amount, 55)

	def test_receipt_submit_requires_donation_rows(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

	def test_receipt_submit_rejects_cross_donor_and_unpaid_donations(self) -> None:
		donor = self._donor()
		other_donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		other_donation = self._donation(other_donor, fiscal_year, amount=60)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": other_donation.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

		unpaid = self._donation(donor, fiscal_year, amount=61, paid=0)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": unpaid.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			receipt.submit()

	def test_receipt_submit_rejects_already_receipted_donation(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=62)
		first_receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)
		first_receipt.submit()

		second_receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			second_receipt.submit()

	def test_receipt_submit_accepts_string_period_dates_from_form_payload(self) -> None:
		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")

		donation = self._donation(donor, fiscal_year, amount=64)
		fy = frappe.get_doc("Fiscal Year", fiscal_year)
		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"donor": donor.name,
				"fiscal_year": fiscal_year,
				"period_from": str(fy.year_start_date),
				"period_to": str(fy.year_end_date),
				"country": self._country(),
				"language": "de",
				"donations": [{"donation": donation.name}],
			}
		).insert(ignore_permissions=True)

		receipt.period_from = str(receipt.period_from)
		receipt.period_to = str(receipt.period_to)
		receipt.submit()

		self.assertEqual(receipt.docstatus, 1)

	def test_yearly_receipt_generation_excludes_existing_draft_rows(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			_create_yearly_receipt_batch,
		)

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		donation = self._donation(donor, fiscal_year, amount=63)
		fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)

		kwargs = {
			"fiscal_year": fiscal_year,
			"period_from": str(fiscal_year_doc.year_start_date),
			"period_to": str(fiscal_year_doc.year_end_date),
			"country": self._country(),
			"language": "de",
		}
		with patch(
			"non_profit.non_profit.doctype.donation_receipt.donation_receipt._yearly_receipt_candidates",
			return_value=[frappe._dict(name=donation.name)],
		):
			first = _create_yearly_receipt_batch(**kwargs)
			second = _create_yearly_receipt_batch(**kwargs)

		self.assertGreaterEqual(first["created"], 1)
		self.assertEqual(second["created"], 0)

	def test_yearly_receipt_public_entry_queues_bounded_job(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			YEARLY_RECEIPT_JOB,
			generate_yearly_receipts,
		)

		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		with patch.object(frappe, "enqueue") as enqueue:
			result = generate_yearly_receipts(fiscal_year=fiscal_year, country=self._country())

		self.assertTrue(result["queued"])
		self.assertEqual(result["created"], 0)
		self.assertEqual(enqueue.call_args.args[0], YEARLY_RECEIPT_JOB)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertTrue(enqueue.call_args.kwargs["deduplicate"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[generate_yearly_receipts], ["POST"])

	def test_yearly_page_deadlock_rolls_back_before_replaying_same_cursor(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt import donation_receipt as receipt_module

		kwargs = {
			"fiscal_year": "2026",
			"period_from": "2026-01-01",
			"period_to": "2026-12-31",
			"country": "Switzerland",
			"language": "de",
			"cursor": "DONATION-CURSOR",
		}
		expected = {"created": 0, "receipts": ["RECEIPT-CURRENT"], "next_cursor": None}
		deadlock = frappe.QueryDeadlockError((1020, "Record has changed since last read"))
		with (
			patch.object(
				receipt_module,
				"_create_yearly_receipt_batch_once",
				side_effect=[deadlock, expected],
			) as page_operation,
			patch.object(receipt_module.frappe.db, "rollback") as rollback,
			patch.object(receipt_module.time, "sleep") as sleep,
		):
			result = receipt_module._create_yearly_receipt_batch(**kwargs)

		self.assertIs(result, expected)
		self.assertEqual(page_operation.call_count, 2)
		self.assertEqual(page_operation.call_args_list[0], page_operation.call_args_list[1])
		rollback.assert_called_once_with()
		sleep.assert_called_once_with(0.25)

	def test_yearly_page_deadlock_retry_is_bounded(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt import donation_receipt as receipt_module

		deadlock = frappe.QueryDeadlockError((1213, "Deadlock found when trying to get lock"))
		with (
			patch.object(
				receipt_module,
				"_create_yearly_receipt_batch_once",
				side_effect=deadlock,
			) as page_operation,
			patch.object(receipt_module.frappe.db, "rollback") as rollback,
			patch.object(receipt_module.time, "sleep") as sleep,
			self.assertRaises(frappe.QueryDeadlockError),
		):
			receipt_module._create_yearly_receipt_batch(
				fiscal_year="2026",
				period_from="2026-01-01",
				period_to="2026-12-31",
				country="Switzerland",
				language="de",
				cursor="DONATION-CURSOR",
			)

		self.assertEqual(page_operation.call_count, receipt_module.YEARLY_RECEIPT_DEADLOCK_MAX_ATTEMPTS)
		self.assertEqual(rollback.call_count, receipt_module.YEARLY_RECEIPT_DEADLOCK_MAX_ATTEMPTS)
		self.assertEqual([item.args[0] for item in sleep.call_args_list], [0.25, 0.5])

	def test_201_donations_in_one_group_reuse_one_draft_across_cursor_pages(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			YEARLY_RECEIPT_BATCH_SIZE,
			_create_yearly_receipt_batch,
		)

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
		company = self._company()
		token = frappe.generate_hash(length=8)
		donation_names = []
		for index in range(YEARLY_RECEIPT_BATCH_SIZE + 1):
			donation = frappe.new_doc("Donation")
			donation.name = f"NP-RCP-BATCH-{token}-{index:03}"
			donation.naming_series = "NPO-DTN-.YYYY.-"
			donation.donor = donor.name
			donation.donor_name = donor.donor_name
			donation.company = company
			donation.date = fiscal_year_doc.year_start_date
			donation.amount = 1
			donation.paid = 1
			donation.docstatus = 1
			donation.db_insert()
			donation_names.append(donation.name)

		kwargs = {
			"fiscal_year": fiscal_year,
			"period_from": str(fiscal_year_doc.year_start_date),
			"period_to": str(fiscal_year_doc.year_end_date),
			"country": self._country(),
			"language": "de",
		}
		pages = [
			[frappe._dict(name=name) for name in donation_names[:YEARLY_RECEIPT_BATCH_SIZE]],
			[frappe._dict(name=donation_names[-1])],
		]
		with patch(
			"non_profit.non_profit.doctype.donation_receipt.donation_receipt._yearly_receipt_candidates",
			side_effect=pages,
		):
			first = _create_yearly_receipt_batch(**kwargs)
			second = _create_yearly_receipt_batch(**kwargs, cursor=first["next_cursor"])

		self.assertEqual(first["created"], 1)
		self.assertEqual(second["created"], 0)
		self.assertEqual(second["receipts"], first["receipts"])
		self.assertEqual(
			frappe.db.count("Donation Receipt Item", {"parent": first["receipts"][0]}),
			YEARLY_RECEIPT_BATCH_SIZE + 1,
		)

	def test_yearly_group_key_separates_company_currency_donor_country_and_period(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			_yearly_receipt_group_key,
		)

		donation = frappe._dict(company="Company A", donor="DONOR-A")
		base = _yearly_receipt_group_key(
			donation,
			currency="CHF",
			country="Switzerland",
			period_from="2026-01-01",
			period_to="2026-12-31",
		)
		self.assertNotEqual(
			base,
			_yearly_receipt_group_key(
				frappe._dict(company="Company B", donor="DONOR-A"),
				currency="EUR",
				country="Switzerland",
				period_from="2026-01-01",
				period_to="2026-12-31",
			),
		)
		self.assertEqual(
			base,
			("Company A", "CHF", "DONOR-A", "Switzerland", "2026-01-01", "2026-12-31"),
		)

	def test_yearly_group_append_revalidates_company_currency_and_donor(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			_create_or_extend_yearly_receipt_group,
		)

		group_key = ("Company A", "CHF", "DONOR-A", "Switzerland", "2026-01-01", "2026-12-31")
		donation = frappe._dict(
			name="DONATION-A",
			company="Company A",
			donor="DONOR-A",
			docstatus=1,
			paid=1,
			date="2026-06-01",
			receipt=None,
		)
		context = {
			"donations": {donation.name: donation},
			"active_receipts": {},
			"company_currencies": {"Company A": "EUR"},
		}
		with self.assertRaisesRegex(frappe.ValidationError, "Company currency changed"):
			_create_or_extend_yearly_receipt_group(
				fiscal_year="2026",
				language="de",
				group_key=group_key,
				donations=[donation],
				context=context,
			)

		donation.donor = "DONOR-B"
		context["company_currencies"]["Company A"] = "CHF"
		with self.assertRaisesRegex(frappe.ValidationError, "changed receipt group"):
			_create_or_extend_yearly_receipt_group(
				fiscal_year="2026",
				language="de",
				group_key=group_key,
				donations=[donation],
				context=context,
			)

	def test_bulk_context_query_count_does_not_scale_with_donation_rows(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			_load_donation_receipt_context,
		)

		donor = self._donor()
		fiscal_year = self._fiscal_year()
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		donations = [self._donation(donor, fiscal_year, amount=amount) for amount in (10, 20, 30)]

		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			context = _load_donation_receipt_context([donation.name for donation in donations])

		self.assertEqual(set(context["donations"]), {donation.name for donation in donations})
		self.assertLessEqual(sql.call_count, 3)

	def test_submit_lock_discards_prelock_ownership_context(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import DonationReceipt

		receipt = DonationReceipt({"doctype": "Donation Receipt"})
		receipt.append("donations", {"donation": "DON-NOT-PERSISTED"})
		receipt.flags.donation_receipt_context = {"stale": True}
		current_context = {
			"donations": {},
			"active_receipts": {},
			"company_currencies": {},
		}

		with patch(
			"non_profit.non_profit.doctype.donation_receipt.donation_receipt._load_locked_donation_receipt_context",
			return_value=current_context,
		) as load_locked:
			result = receipt._lock_donations_for_submit()

		self.assertIs(result, current_context)
		load_locked.assert_called_once_with(["DON-NOT-PERSISTED"], current_receipt=None)
		self.assertIs(receipt.flags.donation_receipt_context["context"], current_context)

	def test_current_locked_ownership_rejects_competing_receipt(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import DonationReceipt

		receipt = DonationReceipt(
			{
				"doctype": "Donation Receipt",
				"name": "RECEIPT-WAITER",
				"donor": "DONOR-1",
				"company": "Company A",
				"currency": "CHF",
				"period_from": "2026-01-01",
				"period_to": "2026-12-31",
				"donations": [{"donation": "DONATION-1"}],
			}
		)
		context = {
			"donations": {
				"DONATION-1": frappe._dict(
					name="DONATION-1",
					donor="DONOR-1",
					company="Company A",
					docstatus=1,
					paid=1,
					date="2026-05-01",
					receipt=None,
				)
			},
			"active_receipts": {"DONATION-1": "RECEIPT-WINNER"},
			"company_currencies": {"Company A": "CHF"},
		}

		with self.assertRaisesRegex(frappe.ValidationError, "RECEIPT-WINNER"):
			receipt._validate_donations_for_submit(context)

	def test_send_requires_submitted_swiss_receipt_and_configured_format(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import DonationReceipt

		receipt = DonationReceipt(
			{
				"doctype": "Donation Receipt",
				"name": "RECEIPT-SWISS",
				"docstatus": 1,
				"status": "Issued",
				"country": "Switzerland",
				"email": "donor@example.org",
				"donor_name": "Donor",
				"fiscal_year": "2026",
				"company": "Company A",
				"currency": "CHF",
			}
		)
		with (
			patch.object(receipt, "check_permission"),
			patch.object(receipt, "_bind_delivery_addresses"),
			patch(
				"non_profit.non_profit.doctype.donation_receipt.donation_receipt._approved_swiss_print_format",
				return_value="Approved Swiss Receipt",
			),
			patch.object(frappe, "attach_print", return_value={"fname": "receipt.pdf"}) as attach_print,
			patch.object(frappe, "sendmail") as sendmail,
			patch.object(receipt, "db_set"),
		):
			self.assertTrue(receipt.send_to_donor())

		attach_print.assert_called_once_with(
			"Donation Receipt", "RECEIPT-SWISS", print_format="Approved Swiss Receipt"
		)
		sendmail.assert_called_once()

		draft = DonationReceipt({"doctype": "Donation Receipt", "docstatus": 0, "status": "Draft"})
		with patch.object(draft, "check_permission"):
			with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
				draft.send_to_donor()

	def test_german_or_missing_format_is_never_accepted_for_swiss_send(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
			_approved_swiss_print_format,
		)

		with patch.object(frappe.db, "get_single_value", return_value=None):
			with self.assertRaisesRegex(frappe.ValidationError, "operator-approved Swiss"):
				_approved_swiss_print_format()
		with patch.object(frappe.db, "get_single_value", return_value="Donation Receipt DE"):
			with self.assertRaisesRegex(frappe.ValidationError, "German legal wording"):
				_approved_swiss_print_format()

	def test_swiss_send_binds_deterministic_issuer_and_recipient_addresses(self) -> None:
		from non_profit.non_profit.doctype.donation_receipt.donation_receipt import DonationReceipt

		receipt = DonationReceipt(
			{
				"doctype": "Donation Receipt",
				"name": "RECEIPT-ADDRESSES",
				"company": "Company A",
				"currency": "CHF",
				"donor": "DONOR-A",
			}
		)
		with (
			patch(
				"non_profit.non_profit.doctype.donation_receipt.donation_receipt._resolve_company_address",
				return_value="COMPANY-ADDRESS",
			) as resolve_company,
			patch(
				"non_profit.non_profit.doctype.donation_receipt.donation_receipt._resolve_recipient_address",
				return_value="RECIPIENT-ADDRESS",
			) as resolve_recipient,
			patch(
				"non_profit.non_profit.doctype.donation_receipt.donation_receipt._validate_postal_address"
			) as validate_address,
			patch.object(receipt, "db_set") as db_set,
		):
			receipt._bind_delivery_addresses()

		resolve_company.assert_called_once_with("Company A", None)
		resolve_recipient.assert_called_once_with("DONOR-A", None)
		self.assertEqual(validate_address.call_args_list[0].kwargs, {"country": "Switzerland"})
		self.assertEqual(validate_address.call_args_list[1].kwargs, {})
		db_set.assert_called_once_with(
			{"company_address": "COMPANY-ADDRESS", "recipient_address": "RECIPIENT-ADDRESS"},
			update_modified=False,
		)

	def _donor(self):
		donor_type = self._donor_type()
		return frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Receipt Donor {frappe.generate_hash(length=8)}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)

	def _donor_type(self) -> str:
		name = f"Receipt Donor Type {frappe.generate_hash(length=8)}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": name}).insert(ignore_permissions=True)
		return name

	def _donation(self, donor, fiscal_year: str, amount: float, paid: int = 1, submit: bool = True):
		fy = frappe.get_doc("Fiscal Year", fiscal_year)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": self._company(),
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"date": fy.year_start_date,
				"amount": amount,
				"paid": paid,
			}
		).insert(ignore_permissions=True)
		if submit:
			donation.submit()
		return donation

	def _fiscal_year(self) -> str | None:
		return frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			"name",
			order_by="year_start_date desc",
		)

	def _company(self) -> str | None:
		return (
			frappe.db.get_single_value("Non Profit Settings", "donation_company")
			or frappe.db.get_single_value("Non Profit Settings", "company")
			or frappe.db.get_value("Company", {}, "name", order_by="name asc")
		)

	def _country(self) -> str | None:
		return (
			"Switzerland"
			if frappe.db.exists("Country", "Switzerland")
			else frappe.db.get_value("Country", {}, "name", order_by="name asc")
		)


class TestDonationReceiptConcurrency(IntegrationTestCase):
	def test_two_workers_reserve_one_donation_once(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The row-lock regression targets MariaDB/InnoDB")

		fiscal_year = frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			"name",
			order_by="year_start_date desc",
		)
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
		company = (
			frappe.db.get_single_value("Non Profit Settings", "donation_company")
			or frappe.db.get_single_value("Non Profit Settings", "company")
			or frappe.db.get_value("Company", {}, "name", order_by="name asc")
		)
		country = (
			"Switzerland"
			if frappe.db.exists("Country", "Switzerland")
			else frappe.db.get_value("Country", {}, "name", order_by="name asc")
		)
		token = frappe.generate_hash(length=8)
		donor_type = f"Receipt Race Type {token}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type}).insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Receipt Race Donor {token}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"company": company,
				"donor": donor.name,
				"donor_name": donor.donor_name,
				"date": fiscal_year_doc.year_start_date,
				"amount": 25,
				"paid": 1,
			}
		).insert(ignore_permissions=True)
		donation.submit()
		frappe.db.commit()

		try:
			barrier = Barrier(2)
			with ThreadPoolExecutor(max_workers=2) as executor:
				results = list(
					executor.map(
						_run_concurrent_receipt_reservation,
						[frappe.local.site, frappe.local.site],
						[donation.name, donation.name],
						[fiscal_year, fiscal_year],
						[str(fiscal_year_doc.year_start_date)] * 2,
						[str(fiscal_year_doc.year_end_date)] * 2,
						[country, country],
						[barrier, barrier],
					)
				)

			self.assertEqual(sorted(results), ["created", "reserved"])
			self.assertEqual(
				frappe.db.count("Donation Receipt Item", {"donation": donation.name}),
				1,
			)
		finally:
			frappe.db.rollback()
			for receipt_name in frappe.get_all(
				"Donation Receipt",
				filters={"donor": donor.name},
				pluck="name",
			):
				frappe.delete_doc("Donation Receipt", receipt_name, ignore_permissions=True)
			if frappe.db.exists("Donation", donation.name):
				donation.reload()
				if donation.docstatus == 1:
					donation.cancel()
				frappe.delete_doc("Donation", donation.name, ignore_permissions=True)
			if frappe.db.exists("Donor", donor.name):
				frappe.delete_doc("Donor", donor.name, ignore_permissions=True)
			if frappe.db.exists("Donor Type", donor_type):
				frappe.delete_doc("Donor Type", donor_type, ignore_permissions=True)
			frappe.db.commit()

	def test_disjoint_cursor_pages_preserve_all_rows_on_same_draft(self) -> None:
		if frappe.db.db_type != "mariadb":
			self.skipTest("The repeatable-read child-row regression targets MariaDB/InnoDB")

		fiscal_year = frappe.db.get_value(
			"Fiscal Year",
			{"disabled": 0},
			"name",
			order_by="year_start_date desc",
		)
		if not fiscal_year:
			self.skipTest("No active Fiscal Year configured")
		fiscal_year_doc = frappe.get_doc("Fiscal Year", fiscal_year)
		company = (
			frappe.db.get_single_value("Non Profit Settings", "donation_company")
			or frappe.db.get_single_value("Non Profit Settings", "company")
			or frappe.db.get_value("Company", {}, "name", order_by="name asc")
		)
		if not company:
			self.skipTest("No Company is available for receipt generation")
		currency = frappe.db.get_value("Company", company, "default_currency")
		country = (
			"Switzerland"
			if frappe.db.exists("Country", "Switzerland")
			else frappe.db.get_value("Country", {}, "name", order_by="name asc")
		)
		if not currency or not country:
			self.skipTest("Receipt accounting or country defaults are unavailable")

		token = frappe.generate_hash(length=8)
		donor_type = f"Receipt Page Race Type {token}"
		frappe.get_doc({"doctype": "Donor Type", "donor_type": donor_type}).insert(ignore_permissions=True)
		donor = frappe.get_doc(
			{
				"doctype": "Donor",
				"donor_name": f"Receipt Page Race Donor {token}",
				"donor_type": donor_type,
			}
		).insert(ignore_permissions=True)
		donations = {}
		for label, amount in (("BASE", 10), ("PAGE-A", 20), ("PAGE-B", 30)):
			donation = frappe.get_doc(
				{
					"doctype": "Donation",
					"company": company,
					"donor": donor.name,
					"donor_name": donor.donor_name,
					"date": fiscal_year_doc.year_start_date,
					"amount": amount,
					"paid": 1,
				}
			).insert(ignore_permissions=True)
			donation.submit()
			donations[label] = donation

		receipt = frappe.get_doc(
			{
				"doctype": "Donation Receipt",
				"naming_series": "NPO-DRCPT-DE-.YYYY.-",
				"donor": donor.name,
				"company": company,
				"currency": currency,
				"fiscal_year": fiscal_year,
				"period_from": fiscal_year_doc.year_start_date,
				"period_to": fiscal_year_doc.year_end_date,
				"country": country,
				"language": "de",
				"donations": [{"donation": donations["BASE"].name}],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		cursors = [f"PAGE-A-{token}", f"PAGE-B-{token}"]
		page_by_cursor = {
			cursors[0]: donations["PAGE-A"].name,
			cursors[1]: donations["PAGE-B"].name,
		}

		def disjoint_page(filters):
			return [frappe._dict(name=page_by_cursor[filters["name"][1]])]

		try:
			barrier = Barrier(2)
			with patch(
				"non_profit.non_profit.doctype.donation_receipt.donation_receipt._yearly_receipt_candidates",
				side_effect=disjoint_page,
			):
				with ThreadPoolExecutor(max_workers=2) as executor:
					results = list(
						executor.map(
							_run_concurrent_yearly_cursor_page,
							[frappe.local.site, frappe.local.site],
							[receipt.name, receipt.name],
							cursors,
							[fiscal_year, fiscal_year],
							[str(fiscal_year_doc.year_start_date)] * 2,
							[str(fiscal_year_doc.year_end_date)] * 2,
							[country, country],
							[barrier, barrier],
						)
					)

			self.assertEqual([result["created"] for result in results], [0, 0])
			self.assertEqual([result["receipts"] for result in results], [[receipt.name], [receipt.name]])
			stored_donations = frappe.get_all(
				"Donation Receipt Item",
				filters={"parent": receipt.name, "parenttype": "Donation Receipt"},
				pluck="donation",
				order_by="idx asc",
			)
			self.assertEqual(len(stored_donations), 3)
			self.assertCountEqual(stored_donations, [donation.name for donation in donations.values()])
		finally:
			frappe.db.rollback()
			for receipt_name in frappe.get_all(
				"Donation Receipt",
				filters={"donor": donor.name},
				pluck="name",
			):
				frappe.delete_doc("Donation Receipt", receipt_name, ignore_permissions=True)
			for donation in donations.values():
				if not frappe.db.exists("Donation", donation.name):
					continue
				current_donation = frappe.get_doc("Donation", donation.name)
				if current_donation.docstatus == 1:
					current_donation.cancel()
				frappe.delete_doc("Donation", donation.name, ignore_permissions=True)
			if frappe.db.exists("Donor", donor.name):
				frappe.delete_doc("Donor", donor.name, ignore_permissions=True)
			if frappe.db.exists("Donor Type", donor_type):
				frappe.delete_doc("Donor Type", donor_type, ignore_permissions=True)
			frappe.db.commit()


def _run_concurrent_receipt_reservation(
	site: str,
	donation_name: str,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	barrier: Barrier,
) -> str:
	from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
		_create_or_extend_yearly_receipt_group,
		_eligible_for_yearly_receipt,
		_load_locked_donation_receipt_context,
		_yearly_receipt_group_key,
	)

	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		barrier.wait(timeout=30)
		context = _load_locked_donation_receipt_context([donation_name])
		donation = context["donations"].get(donation_name)
		if not _eligible_for_yearly_receipt(
			donation,
			context["active_receipts"],
			frappe.utils.getdate(period_from),
			frappe.utils.getdate(period_to),
		):
			frappe.db.rollback()
			return "reserved"
		currency = context["company_currencies"][donation.company]
		group_key = _yearly_receipt_group_key(
			donation,
			currency=currency,
			country=country,
			period_from=period_from,
			period_to=period_to,
		)
		_create_or_extend_yearly_receipt_group(
			fiscal_year=fiscal_year,
			language="de",
			group_key=group_key,
			donations=[donation],
			context=context,
		)
		frappe.db.commit()
		return "created"
	finally:
		frappe.destroy()


def _run_concurrent_yearly_cursor_page(
	site: str,
	receipt_name: str,
	cursor: str,
	fiscal_year: str,
	period_from: str,
	period_to: str,
	country: str,
	barrier: Barrier,
) -> dict:
	from non_profit.non_profit.doctype.donation_receipt.donation_receipt import (
		_create_yearly_receipt_batch,
	)

	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		# Both pages begin with the same old child snapshot before either waits
		# for the exact-group draft lock.
		frappe.get_all(
			"Donation Receipt Item",
			filters={"parent": receipt_name, "parenttype": "Donation Receipt"},
			fields=["name"],
			order_by="idx asc",
			limit_page_length=0,
		)
		barrier.wait(timeout=30)
		result = _create_yearly_receipt_batch(
			fiscal_year=fiscal_year,
			period_from=period_from,
			period_to=period_to,
			country=country,
			language="de",
			cursor=cursor,
		)
		frappe.db.commit()
		return result
	except BaseException:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()
