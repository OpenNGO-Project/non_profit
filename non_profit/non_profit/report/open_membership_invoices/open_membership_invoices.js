frappe.query_reports["Open Membership Invoices"] = {
    filters: [
        {
            fieldname: "membership_type",
            label: __("Membership Type"),
            fieldtype: "Link",
            options: "Membership Type",
            default: "ÖDP Mitglied",
            reqd: 1,
        },
        {
            fieldname: "chapter",
            label: __("Chapter"),
            fieldtype: "Link",
            options: "Chapter",
        },
    ],
};
