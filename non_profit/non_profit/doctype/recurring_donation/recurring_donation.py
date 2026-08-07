import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_years, cint, cstr, escape_html, getdate, now_datetime, nowdate

from non_profit.non_profit.doctype.donor.donor import get_donor_email
from non_profit.non_profit.recurring_notices import (
	CANCELLED,
	PAYMENT_FAILED,
	SIGNUP,
	notify,
)

PROVIDER_HOOK = "non_profit_recurring_donation_providers"
PROVIDER_LINK_FIELDS = (
	"payment_provider",
	"provider_subscription_id",
	"provider_reference",
	"provider_account",
)
PROVIDER_MANAGED_IMMUTABLE_FIELDS = (
	"company",
	"status",
	"amount",
	"currency",
	"frequency",
	*PROVIDER_LINK_FIELDS,
)

# Provider-reported lifecycle, mapped to schedule status. Two are easy to get
# wrong and both cost money:
#   retrying  a charge failed and the provider WILL try again — chasing the
#             donor now annoys someone who is about to pay successfully
#   ending    the donor cancelled but the remaining charges still follow, so
#             installments must keep being recorded in this state
PROVIDER_STATUS_MAP = {
	"active": "Active",
	"overdue": "Payment Retrying",
	"failed": "Payment Failed",
	"in_notice": "Ending",
	"cancelled": "Cancelled",
}

# States in which the provider may still charge. `Ending` belongs here: the
# donor gave notice, not a refund.
COLLECTING_STATUSES = ("Active", "Payment Retrying", "Ending")
PROVIDER_STATUS_TRANSITIONS = {
	"Pending Mandate": frozenset({"Active", "Payment Retrying", "Payment Failed", "Ending", "Cancelled"}),
	"Active": frozenset({"Payment Retrying", "Payment Failed", "Ending", "Cancelled"}),
	"Payment Retrying": frozenset({"Active", "Payment Failed", "Ending", "Cancelled"}),
	"Ending": frozenset({"Payment Failed", "Cancelled"}),
	"Payment Failed": frozenset(),
	"Cancelled": frozenset(),
}


class RecurringDonation(Document):
	def validate(self):
		self._validate_provider_managed_fields()
		if self.donor:
			self.email = get_donor_email(self.donor) or self.email
		if not self.start_date:
			self.start_date = nowdate()
		if not self.next_date:
			self.next_date = self.start_date
		if self.end_date and self.start_date and self.end_date < self.start_date:
			frappe.throw(_("End Date cannot be before Start Date"))
		if not self.currency:
			self.currency = self._default_currency()

	def _validate_provider_managed_fields(self) -> None:
		before = self.get_doc_before_save()
		if not before or not (_has_provider_state(before) or _has_provider_state(self)):
			return
		changed = [
			fieldname for fieldname in PROVIDER_MANAGED_IMMUTABLE_FIELDS if self.has_value_changed(fieldname)
		]
		if changed:
			frappe.throw(
				_("Provider-managed schedule fields cannot be changed directly: {0}.").format(
					", ".join(frappe.unscrub(fieldname) for fieldname in changed)
				)
			)

	def _default_currency(self) -> str:
		"""The Company's own currency, not a global guess.

		This used to fall back to "EUR" while the deployments using it are
		Swiss — a wrong currency here is charged, not just displayed.
		"""
		company_currency = (
			frappe.get_cached_value("Company", self.company, "default_currency") if self.company else None
		)
		return company_currency or frappe.db.get_default("currency") or "CHF"

	# ------------------------------------------------------------- provider

	@property
	def is_provider_backed(self) -> bool:
		"""Whether a provider subscription is completely linked."""
		return all(cstr(self.get(fieldname)).strip() for fieldname in PROVIDER_LINK_FIELDS)

	@property
	def is_provider_managed(self) -> bool:
		"""Whether any provider state reserves this schedule from local fan-out.

		A provider is already responsible while a mandate is pending and before it
		has minted the subscription id. Treating that incomplete window as local
		would create an installment in parallel with the provider signup.
		"""
		return _has_provider_state(self)

	def advance_next_date(self):
		if self.frequency == "Monthly":
			self.next_date = add_months(getdate(self.next_date), 1)
		elif self.frequency == "Quarterly":
			self.next_date = add_months(getdate(self.next_date), 3)
		elif self.frequency == "Yearly":
			self.next_date = add_years(getdate(self.next_date), 1)
		if self.end_date and getdate(self.next_date) > getdate(self.end_date):
			self.status = "Cancelled"

	def create_donation(self, mark_paid: bool = False, **values):
		donation = frappe.get_doc(
			{
				"doctype": "Donation",
				"donor": self.donor,
				"donor_name": self.donor_name,
				"email": self.email,
				"company": self.company,
				"date": self.next_date,
				"amount": self.amount,
				"mode_of_payment": self.mode_of_payment,
				"campaign": self.campaign,
				"recurring_donation": self.name,
				**values,
			}
		)
		donation.flags.ignore_permissions = True
		donation.insert()
		donation.submit()
		if mark_paid:
			# Donation owns the complete first-payment state machine: accounting,
			# rollback of the paid flag on failure, acknowledgement dispatch, and
			# donor/Major Gift roll-ups. Provider installments must not maintain a
			# second, partial version of those side effects.
			donation.run_method(
				"on_payment_authorized",
				"Completed",
				payment_date=values.get("date"),
			)
		return donation

	@frappe.whitelist(methods=["POST"])
	def create_next_donation(self) -> str:
		# run_doc_method only enforces read permission; inserting and
		# submitting a Donation is a write-level action.
		current = _lock_recurring_donation(self.name)
		current.check_permission("write")
		if current.is_provider_managed:
			# The provider decides when this is charged. Generating an
			# installment by hand here would invent money that never moved.
			frappe.throw(
				_("{0} charges this schedule. Installments are recorded when it reports them.").format(
					current.payment_provider
				)
			)
		donation = current._get_or_create_current_donation()
		current.advance_next_date()
		current.save()
		return donation.name

	def _get_or_create_current_donation(self):
		existing = frappe.db.get_value(
			"Donation",
			{
				"recurring_donation": self.name,
				"date": self.next_date,
				"docstatus": ["<", 2],
			},
			"name",
			order_by="creation asc",
			for_update=True,
		)
		return (
			frappe.get_doc("Donation", existing, for_update=True)
			if existing
			else self.create_donation(mark_paid=False)
		)

	# --------------------------------------------------- provider operations

	@frappe.whitelist(methods=["POST"])
	def change_amount(self, amount: str | float | None) -> str:
		"""Ask the provider to charge a different amount from the next interval on."""
		current = _lock_recurring_donation(self.name)
		current.check_permission("write")
		new_amount = _validated_amount(amount)
		if current.is_provider_managed and not current.is_provider_backed:
			frappe.throw(_("This provider-managed schedule is incomplete and cannot be changed safely."))
		if not current.is_provider_backed:
			current.db_set("amount", new_amount)
			return cstr(new_amount)
		if current.status not in COLLECTING_STATUSES:
			frappe.throw(_("This schedule is {0} and is no longer charged.").format(_(current.status)))

		previous = current.amount
		_dispatch_provider(current, "change_amount", amount=new_amount)
		current.db_set("amount", new_amount)
		current.add_comment(
			"Comment",
			_("Amount changed from {0} to {1}. The provider applies it from the next charge.").format(
				previous, new_amount
			),
		)
		return cstr(new_amount)

	@frappe.whitelist(methods=["POST"])
	def cancel_schedule(self) -> str:
		"""Stop future charges. Immediate — no provider here offers a grace period."""
		current = _lock_recurring_donation(self.name)
		current.check_permission("write")
		if current.status == "Cancelled":
			return current.status
		if current.is_provider_managed and not current.is_provider_backed:
			frappe.throw(_("This provider-managed schedule is incomplete and cannot be cancelled safely."))
		if current.is_provider_backed:
			_dispatch_provider(current, "cancel")
		current.db_set("status", "Cancelled")
		current.add_comment("Comment", _("Schedule cancelled by {0}.").format(frappe.session.user))
		notify(current, CANCELLED)
		return "Cancelled"

	@frappe.whitelist(methods=["POST"])
	def retire_abandoned_pending_mandate(self) -> str:
		"""Retire a checkout reservation only after its provider proves it is safe."""
		current = _lock_recurring_donation(self.name)
		current.check_permission("write")
		if current.status == "Cancelled":
			return current.status
		if current.status != "Pending Mandate" or not current.is_provider_managed:
			frappe.throw(_("Only an incomplete Pending Mandate can use abandoned-checkout recovery."))
		if current.provider_subscription_id:
			frappe.throw(
				_("This schedule already has a provider subscription and cannot be retired locally.")
			)

		evidence = _dispatch_provider(current, "verify_abandoned_pending_mandate")
		if not isinstance(evidence, dict) or evidence.get("safe_to_retire") is not True:
			frappe.throw(_("The payment provider did not prove that this pending mandate is safe to retire."))

		current.db_set("status", "Cancelled")
		current.add_comment(
			"Comment",
			_("Abandoned Pending Mandate retired by {0} after provider verification: {1}").format(
				escape_html(frappe.session.user),
				escape_html(frappe.as_json(evidence)),
			),
		)
		# No cancellation notice: the provider proved that no mandate or payment
		# exists, so telling the donor an instruction was stopped would be false.
		return "Cancelled"

	# ------------------------------------------------- provider event intake

	def record_provider_installment(
		self,
		*,
		transaction_id: str,
		paid_on=None,
		amount=None,
		donation_values: dict | None = None,
	):
		"""Record one charge the provider actually took.

		Idempotency keys on the provider's transaction id rather than the date:
		a retried charge inside one period is a second attempt at the same
		installment and must not create two Donations, while a genuine second
		charge in a period must not be swallowed. Provider webhooks are retried
		for days, so this runs many times per real payment.
		"""
		transaction_id = cstr(transaction_id).strip()
		if not transaction_id:
			frappe.throw(_("A provider installment needs the provider's transaction id."))

		existing = frappe.db.get_value(
			"Donation",
			{"recurring_donation": self.name, "payment_id": transaction_id},
			"name",
			order_by="creation asc",
			for_update=True,
		)
		if existing:
			# A cancelled Donation remains the immutable evidence that this provider
			# transaction was already recorded. Replacing it on webhook replay would
			# post the same money a second time.
			return frappe.get_doc("Donation", existing, for_update=True)

		donation = self.create_donation(
			mark_paid=True,
			date=getdate(paid_on) if paid_on else nowdate(),
			amount=amount if amount is not None else self.amount,
			payment_id=transaction_id,
			**(donation_values or {}),
		)
		self.db_set({"failure_count": 0, "last_decline_reason": None})
		return donation

	def apply_provider_status(self, provider_status: str, *, next_payment=None) -> str | None:
		"""Mirror the provider's own view of the instruction."""
		mapped = PROVIDER_STATUS_MAP.get(cstr(provider_status).strip().lower())
		if not mapped:
			return None
		previous = self.status
		if mapped != previous and mapped not in PROVIDER_STATUS_TRANSITIONS.get(previous, frozenset()):
			frappe.log_error(
				title="Recurring Donation: stale provider status ignored",
				message=frappe.as_json(
					{"schedule": self.name, "stored_status": previous, "provider_status": mapped}
				),
			)
			return None
		updates = {}
		if next_payment:
			updates["provider_next_payment"] = getdate(next_payment)
			# next_date is a mirror once a provider owns the schedule, so keep the
			# two from drifting into contradicting each other in reports.
			updates["next_date"] = getdate(next_payment)
		if mapped != previous:
			updates["status"] = mapped
		if updates:
			self.db_set(updates)
		if mapped != previous:
			# `Payment Retrying` deliberately sends nothing: the provider is still
			# trying, and telling a donor their payment failed while it is about to
			# succeed is worse than silence.
			if mapped == "Payment Failed":
				notify(self, PAYMENT_FAILED)
			elif mapped == "Cancelled":
				notify(self, CANCELLED)
			elif previous == "Pending Mandate" and mapped == "Active":
				# The mandate is confirmed the first time the provider reports it
				# active, not when the schedule row was reserved.
				notify(self, SIGNUP)
		return mapped

	def record_provider_failure(self, *, reason: str | None = None, provider_status: str | None = None):
		self.db_set(
			{
				"failure_count": cint(self.failure_count) + 1,
				"last_failure_on": now_datetime(),
				"last_decline_reason": cstr(reason)[:500] or None,
			}
		)
		if provider_status:
			self.apply_provider_status(provider_status)


def _validated_amount(amount) -> float:
	from non_profit.non_profit.utils import validate_public_donation_amount

	return validate_public_donation_amount(cstr(amount))


def _has_provider_state(schedule) -> bool:
	return any(cstr(schedule.get(fieldname)).strip() for fieldname in PROVIDER_LINK_FIELDS)


def _dispatch_provider(schedule, action: str, **kwargs):
	"""Hand a provider-side operation to the app that owns the integration.

	This app is a public substrate and must not import the private integration
	apps, so it never talks to a payment provider directly. An unclaimed action
	is an error, not a no-op: silently doing nothing would leave the donor
	charged the old amount while the record claims otherwise.
	"""
	for provider in frappe.get_hooks(PROVIDER_HOOK):
		result = frappe.get_attr(provider)(action=action, schedule=schedule, **kwargs)
		if result is True or isinstance(result, dict):
			return result
	frappe.throw(
		_("No integration is registered to {0} a {1} subscription.").format(
			action.replace("_", " "), schedule.payment_provider or _("provider")
		)
	)


def process_recurring_donations():
	"""Daily scheduler: fan out due recurring donations into Donation records.

	Provider-backed schedules are excluded, and that exclusion is the reason
	double installments are impossible rather than merely unlikely: when a
	provider owns the schedule it reports every charge, and a second generator
	running on a date would duplicate each one.
	"""
	today = getdate(nowdate())
	due = frappe.get_all(
		"Recurring Donation",
		filters={
			"status": "Active",
			"next_date": ["<=", today],
			"payment_provider": ["in", ["", None]],
		},
		fields=["name"],
		order_by="name asc",
	)
	for candidate in due:
		name = candidate.name
		try:
			if not _process_due_recurring_donation(name, today):
				frappe.db.rollback()
				continue
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
		except Exception:
			frappe.log_error(title=f"Recurring Donation fan-out failed: {name}")
			frappe.db.rollback()


def _process_due_recurring_donation(name: str, today) -> str | None:
	recurring = _lock_recurring_donation(name)
	if recurring.is_provider_managed:
		return None
	if recurring.status != "Active" or not recurring.next_date or getdate(recurring.next_date) > today:
		return None
	donation = recurring._get_or_create_current_donation()
	recurring.advance_next_date()
	recurring.save(ignore_permissions=True)
	return donation.name


def _lock_recurring_donation(name: str) -> RecurringDonation:
	"""Return the complete current schedule state from the locking read."""
	return frappe.get_doc("Recurring Donation", name, for_update=True)


def find_by_provider_subscription(
	payment_provider: str,
	subscription_id: str,
	provider_account: str,
) -> str | None:
	"""Resolve a provider's own subscription id to a schedule, or None.

	Ambiguity is refused rather than guessed: two schedules claiming one
	subscription is a data fault, and picking either would attach real money to
	an arbitrary donor.
	"""
	matches = frappe.get_all(
		"Recurring Donation",
		filters={
			"payment_provider": cstr(payment_provider).strip(),
			"provider_subscription_id": cstr(subscription_id).strip(),
			"provider_account": cstr(provider_account).strip(),
		},
		pluck="name",
		limit=2,
	)
	if len(matches) > 1:
		frappe.log_error(
			title="Recurring Donation: ambiguous provider subscription",
			message=frappe.as_json(
				{
					"provider": payment_provider,
					"provider_account": provider_account,
					"subscription": subscription_id,
					"matches": matches,
				}
			),
		)
		return None
	return matches[0] if matches else None


def find_by_provider_reference(
	payment_provider: str,
	provider_reference: str,
	provider_account: str,
) -> str | None:
	"""Resolve the exact provider/account/Integration Request tuple."""
	matches = frappe.get_all(
		"Recurring Donation",
		filters={
			"payment_provider": cstr(payment_provider).strip(),
			"provider_reference": cstr(provider_reference).strip(),
			"provider_account": cstr(provider_account).strip(),
		},
		pluck="name",
		limit=2,
	)
	if len(matches) > 1:
		frappe.log_error(
			title="Recurring Donation: ambiguous provider reference",
			message=frappe.as_json(
				{
					"provider": payment_provider,
					"provider_account": provider_account,
					"provider_reference": provider_reference,
					"matches": matches,
				}
			),
		)
		return None
	return matches[0] if matches else None
