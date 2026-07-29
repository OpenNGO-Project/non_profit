frappe.listview_settings["Member"] = {
	add_fields: ["member_name", "image"],
	primary_action() {
		if (frappe.boot.versions && !frappe.boot.versions.good_connector) {
			show_technical_member_creation_dialog();
			return;
		}
		show_member_creation_dialog();
	},
};

function show_technical_member_creation_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Member and Membership"),
		fields: [
			{
				fieldname: "contact",
				fieldtype: "Link",
				label: __("Contact"),
				options: "Contact",
			},
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
			},
			{
				fieldname: "membership_type",
				fieldtype: "Link",
				label: __("Membership Type"),
				options: "Membership Type",
				reqd: 1,
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			if (!values.contact && !values.customer) {
				frappe.throw(__("Select a Contact or a Customer."));
			}
			submit_member_dialog(dialog, values);
		},
	});
	dialog.show();
}

function show_member_creation_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Member"),
		size: "large",
		fields: [
			{
				fieldname: "member_kind",
				fieldtype: "Select",
				label: __("Member Type"),
				options: "Individual\nOrganization",
				default: "Individual",
				reqd: 1,
				async change() {
					set_member_kind_fields(dialog);
					await load_existing_contact(dialog);
				},
			},
			{
				fieldname: "contact",
				fieldtype: "Link",
				label: __("Existing Contact (Optional)"),
				options: "Contact",
				async change() {
					await load_existing_contact(dialog);
				},
			},
			{
				fieldname: "person_section",
				fieldtype: "Section Break",
				label: __("Person"),
			},
			{
				fieldname: "first_name",
				fieldtype: "Data",
				label: __("First Name"),
				reqd: 1,
			},
			{
				fieldname: "last_name",
				fieldtype: "Data",
				label: __("Last Name"),
				reqd: 1,
			},
			{ fieldname: "person_column", fieldtype: "Column Break" },
			{
				fieldname: "email",
				fieldtype: "Data",
				label: __("Email"),
				options: "Email",
				reqd: 1,
			},
			{
				fieldname: "phone",
				fieldtype: "Data",
				label: __("Phone"),
				options: "Phone",
			},
			{
				fieldname: "organization_section",
				fieldtype: "Section Break",
				label: __("Organization"),
				hidden: 1,
			},
			{
				fieldname: "organization_name",
				fieldtype: "Data",
				label: __("Organization Name"),
				hidden: 1,
			},
			{
				fieldname: "organization_contact_section",
				fieldtype: "Section Break",
				label: __("Optional Contact Person"),
				hidden: 1,
			},
			{
				fieldname: "organization_contact_first_name",
				fieldtype: "Data",
				label: __("Contact Person First Name"),
				hidden: 1,
			},
			{
				fieldname: "organization_contact_last_name",
				fieldtype: "Data",
				label: __("Contact Person Last Name"),
				hidden: 1,
			},
			{ fieldname: "organization_contact_column", fieldtype: "Column Break", hidden: 1 },
			{
				fieldname: "organization_contact_email",
				fieldtype: "Data",
				label: __("Contact Person Email"),
				options: "Email",
				hidden: 1,
			},
			{
				fieldname: "organization_contact_phone",
				fieldtype: "Data",
				label: __("Contact Person Phone"),
				options: "Phone",
				hidden: 1,
			},
			{
				fieldname: "address_section",
				fieldtype: "Section Break",
				label: __("Address"),
			},
			{
				fieldname: "existing_address",
				fieldtype: "Link",
				label: __("Existing Address (Optional)"),
				options: "Address",
				async change() {
					await load_existing_address(dialog);
				},
			},
			{
				fieldname: "address_line1",
				fieldtype: "Data",
				label: __("Street and House Number"),
				reqd: 1,
			},
			{
				fieldname: "postal_code",
				fieldtype: "Data",
				label: __("Postal Code"),
				reqd: 1,
			},
			{ fieldname: "address_column", fieldtype: "Column Break" },
			{
				fieldname: "city",
				fieldtype: "Data",
				label: __("City"),
				reqd: 1,
			},
			{
				fieldname: "country",
				fieldtype: "Link",
				label: __("Country"),
				options: "Country",
				default: frappe.defaults.get_default("country"),
				reqd: 1,
			},
			{
				fieldname: "membership_section",
				fieldtype: "Section Break",
				label: __("Membership"),
			},
			{
				fieldname: "membership_type",
				fieldtype: "Link",
				label: __("Membership Type"),
				options: "Membership Type",
				reqd: 1,
			},
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			validate_member_values(values);
			submit_member_dialog(dialog, values);
		},
	});

	dialog.show();
	set_member_kind_fields(dialog);
	set_contact_fields_read_only(dialog, false);
	set_address_fields_read_only(dialog, false);
}

function submit_member_dialog(dialog, values) {
	dialog.disable_primary_action();
	frappe
		.call({
			method: "non_profit.non_profit.doctype.member.member.create_member_and_membership",
			args: values,
			type: "POST",
			freeze: true,
			freeze_message: __("Creating Member and Membership"),
		})
		.then((r) => {
			const result = r.message || {};
			if (result.member) {
				dialog.hide();
				frappe.set_route("Form", "Member", result.member);
			}
		})
		.always(() => dialog.enable_primary_action());
}

function set_member_kind_fields(dialog) {
	const isIndividual = dialog.get_value("member_kind") === "Individual";
	for (const fieldname of [
		"person_section",
		"first_name",
		"last_name",
		"person_column",
		"email",
		"phone",
	]) {
		dialog.set_df_property(fieldname, "hidden", !isIndividual);
	}
	for (const fieldname of [
		"organization_section",
		"organization_name",
		"organization_contact_section",
		"organization_contact_first_name",
		"organization_contact_last_name",
		"organization_contact_column",
		"organization_contact_email",
		"organization_contact_phone",
	]) {
		dialog.set_df_property(fieldname, "hidden", isIndividual);
	}
	for (const fieldname of [
		"first_name",
		"last_name",
		"email",
		"address_line1",
		"postal_code",
		"city",
		"country",
	]) {
		dialog.set_df_property(fieldname, "reqd", isIndividual);
	}
	dialog.set_df_property("organization_name", "reqd", !isIndividual);
}

async function load_existing_contact(dialog) {
	const contactName = dialog.get_value("contact");
	set_contact_fields_read_only(dialog, Boolean(contactName));
	if (!contactName) {
		return;
	}

	const contact = await frappe.db.get_doc("Contact", contactName);
	const primaryEmail =
		contact.email_id || (contact.email_ids || []).find((row) => row.is_primary)?.email_id;
	if (!primaryEmail) {
		frappe.throw(__("The selected Contact needs a primary email address."));
	}
	const primaryPhone =
		contact.phone ||
		(contact.phone_nos || []).find((row) => row.is_primary_phone)?.phone ||
		contact.phone_nos?.[0]?.phone;
	const isIndividual = dialog.get_value("member_kind") === "Individual";
	const fieldValues = {};
	if (isIndividual) {
		Object.assign(fieldValues, {
			first_name: contact.first_name,
			last_name: contact.last_name,
			email: primaryEmail,
			phone: primaryPhone,
		});
	} else {
		Object.assign(fieldValues, {
			organization_contact_first_name: contact.first_name,
			organization_contact_last_name: contact.last_name,
			organization_contact_email: primaryEmail,
			organization_contact_phone: primaryPhone,
		});
	}
	for (const [fieldname, value] of Object.entries(fieldValues)) {
		await dialog.set_value(fieldname, value || "");
	}
}

function set_contact_fields_read_only(dialog, readOnly) {
	for (const fieldname of [
		"first_name",
		"last_name",
		"email",
		"phone",
		"organization_contact_first_name",
		"organization_contact_last_name",
		"organization_contact_email",
		"organization_contact_phone",
	]) {
		dialog.set_df_property(fieldname, "read_only", readOnly);
	}
}

async function load_existing_address(dialog) {
	const addressName = dialog.get_value("existing_address");
	set_address_fields_read_only(dialog, Boolean(addressName));
	if (!addressName) {
		return;
	}

	const address = await frappe.db.get_doc("Address", addressName);
	for (const [fieldname, value] of Object.entries({
		address_line1: address.address_line1,
		postal_code: address.pincode,
		city: address.city,
		country: address.country,
	})) {
		await dialog.set_value(fieldname, value || "");
	}
}

function set_address_fields_read_only(dialog, readOnly) {
	for (const fieldname of ["address_line1", "postal_code", "city", "country"]) {
		dialog.set_df_property(fieldname, "read_only", readOnly);
	}
}

function validate_member_values(values) {
	if (values.member_kind !== "Organization") {
		return;
	}
	const contactFields = [
		values.organization_contact_first_name,
		values.organization_contact_last_name,
		values.organization_contact_email,
		values.organization_contact_phone,
	];
	if (contactFields.some(Boolean) && contactFields.slice(0, 3).some((value) => !value)) {
		frappe.throw(
			__("Enter first name, last name, and email for the organization contact person.")
		);
	}
	const addressFields = [values.address_line1, values.postal_code, values.city];
	if (addressFields.some(Boolean) && addressFields.some((value) => !value)) {
		frappe.throw(
			__("Street and house number, postal code, and city must be provided together.")
		);
	}
}
