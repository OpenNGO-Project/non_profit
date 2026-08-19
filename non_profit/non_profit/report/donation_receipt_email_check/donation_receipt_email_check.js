frappe.query_reports["Donation Receipt Email Check"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "tax_year",
			label: __("Tax Year"),
			fieldtype: "Int",
			default: new Date().getFullYear() - 1,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "severity" && data) {
			const colour = data.severity === "Blocker" ? "red" : "orange";
			value = `<span style="color:${colour};font-weight:600">${value}</span>`;
		}
		return value;
	},
};
