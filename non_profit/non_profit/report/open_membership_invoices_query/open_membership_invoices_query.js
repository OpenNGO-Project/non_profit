frappe.query_reports["Open Membership Invoices Query"] = {
    filters: [
        {
            fieldname: "membership_type",
            label: __("Membership Type"),
            fieldtype: "Link",
            options: "Membership Type",
        },
        {
            fieldname: "chapter",
            label: __("Chapter"),
            fieldtype: "Link",
            options: "Chapter",
        },
    ],
};
