import frappe


no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	donation_name = frappe.form_dict.get("donation")
	if not donation_name:
		context.donation = None
		return context

	if not frappe.db.exists("Donation", donation_name):
		context.donation = None
		return context

	donation = frappe.get_doc("Donation", donation_name)

	if frappe.request and frappe.request.method == "POST" and not donation.paid:
		donation.flags.ignore_permissions = True
		donation.run_method("on_payment_authorized")
		frappe.db.commit()
		donation.reload()

	context.donation = donation
	return context
