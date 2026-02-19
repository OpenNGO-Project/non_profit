frappe.listview_settings['Membership'] = {
	get_indicator: function(doc) {
		var status = doc.subscription_status;
		if (status === 'Active') {
			return [__('Active'), 'green', 'subscription_status,=,Active'];
		} else if (status === 'Trialing') {
			return [__('New'), 'blue', 'subscription_status,=,Trialing'];
		} else if (status === 'Grace Period') {
			return [__('Pending'), 'orange', 'subscription_status,=,Grace Period'];
		} else if (status === 'Unpaid') {
			return [__('Expired'), 'red', 'subscription_status,=,Unpaid'];
		} else if (status === 'Completed') {
			return [__('Expired'), 'grey', 'subscription_status,=,Completed'];
		} else if (status === 'Cancelled') {
			return [__('Cancelled'), 'red', 'subscription_status,=,Cancelled'];
		} else if (doc.docstatus === 0) {
			return [__('Draft'), 'grey', 'docstatus,=,0'];
		} else if (doc.docstatus === 2) {
			return [__('Cancelled'), 'red', 'docstatus,=,2'];
		} else {
			return [__('Active'), 'blue', 'subscription_status,=,'];
		}
	}
};
