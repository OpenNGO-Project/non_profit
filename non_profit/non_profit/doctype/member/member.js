frappe.ui.form.on('Member', {
    refresh: function(frm) {
        if(!frm.doc.__islocal) {
            frm.add_custom_button(__('Accounting Ledger'), function() {
                frappe.set_route('query-report', 'General Ledger', {party_type: 'Customer', party: frm.doc.customer});
            });

            frm.add_custom_button(__('Accounts Receivable'), function() {
                frappe.set_route('query-report', 'Accounts Receivable', {customer: frm.doc.customer});
            });

            if (typeof erpnext !== 'undefined' && erpnext.utils && erpnext.utils.set_party_dashboard_indicators) {
                erpnext.utils.set_party_dashboard_indicators(frm);
            }

            frm.trigger('show_membership_status');
        }
    },

    show_membership_status: function(frm) {
        frm.call('get_active_memberships').then(r => {
            if (r.message && r.message.length > 0) {
                let primary = r.message[0];
                let status = primary.subscription_status || 'Active';
                let indicator = membership_get_status_indicator(status);
                frm.dashboard.set_headline(indicator.text, indicator.color);
            }
        });
    },

    customer: function(frm) {
        if (frm.doc.customer) {
            frm.call("get_contact_details").then(r => {
                if (r.message) {
                    if (r.message.has_contact) {
                        frm.set_value("contact", r.message.contact);
                        frm.set_value("first_name", r.message.first_name);
                        frm.set_value("last_name", r.message.last_name);
                    } else {
                        frappe.msgprint({
                            title: __("No Contact Found"),
                            message: __("Customer {0} does not have a Contact record. Please create a Contact first.").replace("{0}", frm.doc.customer),
                            indicator: "orange"
                        });
                        frm.set_value("contact", "");
                        frm.set_value("first_name", "");
                        frm.set_value("last_name", "");
                    }
                }
            });
        } else {
            frm.set_value("contact", "");
            frm.set_value("first_name", "");
            frm.set_value("last_name", "");
        }
    }
});

function membership_get_status_indicator(status) {
    const status_map = {
        'Active': {text: __('Active'), color: 'green'},
        'Trialing': {text: __('New'), color: 'blue'},
        'Grace Period': {text: __('Pending'), color: 'orange'},
        'Unpaid': {text: __('Expired'), color: 'red'},
        'Cancelled': {text: __('Cancelled'), color: 'red'},
        'Completed': {text: __('Expired'), color: 'grey'},
    };
    return status_map[status] || {text: status || __('Unknown'), color: 'grey'};
}
