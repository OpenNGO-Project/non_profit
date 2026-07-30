import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Donation Receipt") or not (
		frappe.db.has_column("Donation Receipt", "company")
		and frappe.db.has_column("Donation Receipt", "currency")
	):
		return

	receipt_item = frappe.qb.DocType("Donation Receipt Item")
	donation = frappe.qb.DocType("Donation")
	rows = (
		frappe.qb.from_(receipt_item)
		.inner_join(donation)
		.on(donation.name == receipt_item.donation)
		.select(receipt_item.parent, donation.company)
		.where(receipt_item.parenttype == "Donation Receipt")
		.where(donation.company.isnotnull())
		.orderby(receipt_item.parent)
	).run()
	companies_by_receipt: dict[str, set[str]] = {}
	for receipt_name, company in rows:
		if company:
			companies_by_receipt.setdefault(receipt_name, set()).add(company)

	receipts = frappe.get_all("Donation Receipt", fields=["name", "company", "currency"])
	default_company = frappe.db.get_single_value("Non Profit Settings", "donation_company")
	companies = {receipt.company for receipt in receipts if receipt.company}
	companies.update(company for values in companies_by_receipt.values() for company in values)
	if default_company:
		companies.add(default_company)
	company_currencies = (
		dict(
			frappe.get_all(
				"Company",
				filters={"name": ["in", sorted(companies)]},
				fields=["name", "default_currency"],
				as_list=True,
				limit_page_length=0,
			)
		)
		if companies
		else {}
	)

	for receipt in receipts:
		linked_companies = companies_by_receipt.get(receipt.name, set())
		if len(linked_companies) > 1:
			frappe.log_error(
				title=f"Donation Receipt Company backfill requires review: {receipt.name}",
				message=frappe.as_json({"companies": sorted(linked_companies)}),
			)
			continue
		company = receipt.company or (next(iter(linked_companies)) if linked_companies else default_company)
		if receipt.company and linked_companies and receipt.company not in linked_companies:
			frappe.log_error(
				title=f"Donation Receipt Company backfill conflict: {receipt.name}",
				message=frappe.as_json(
					{"stored_company": receipt.company, "donation_companies": sorted(linked_companies)}
				),
			)
			continue
		expected_currency = company_currencies.get(company)
		if receipt.currency and expected_currency and receipt.currency != expected_currency:
			frappe.log_error(
				title=f"Donation Receipt currency backfill conflict: {receipt.name}",
				message=frappe.as_json(
					{
						"stored_currency": receipt.currency,
						"company": company,
						"company_currency": expected_currency,
					}
				),
			)
		currency = receipt.currency or expected_currency
		updates = {}
		if company and receipt.company != company:
			updates["company"] = company
		if currency and receipt.currency != currency:
			updates["currency"] = currency
		if updates:
			frappe.db.set_value("Donation Receipt", receipt.name, updates, update_modified=False)
