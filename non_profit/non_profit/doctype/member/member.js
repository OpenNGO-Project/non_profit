frappe.ui.form.on('Member', {
    setup: function(frm) {
        frappe.db.get_single_value('Non Profit Settings', 'enable_razorpay_for_memberships').then(val => {
            if (val && (frm.doc.subscription_id || frm.doc.customer_id)) {
                frm.set_df_property('razorpay_details_section', 'hidden', false);
            }
        })
    },

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
        }

        if (frm.doc.subscription) {
            frappe.db.get_value('Subscription', frm.doc.subscription, 'status').then(r => {
                if (r.message) {
                    let status = r.message.status;
                    let indicator = '';
                    if (status === 'Active') {
                        indicator = {text: __('Active'), color: 'green'};
                    } else if (status === 'Cancelled') {
                        indicator = {text: __('Cancelled'), color: 'red'};
                    } else if (status === 'Unpaid' || status === 'Grace Period') {
                        indicator = {text: __('Payment Due'), color: 'orange'};
                    }
                    if (indicator) {
                        frm.dashboard.set_headline(indicator.text, indicator.color);
                    }
                }
            });
        }
    },

    customer: function(frm) {
        if (frm.doc.customer) {
            frm.call("get_contact_details").then(r => {
                if (r.message) {
                    if (r.message.has_contact) {
                        frm.set_value("first_name", r.message.first_name);
                        frm.set_value("last_name", r.message.last_name);
                    } else {
                        frappe.msgprint({
                            title: __("No Contact Found"),
                            message: __("Customer {0} does not have a Contact record. Please create a Contact first.").replace("{0}", frm.doc.customer),
                            indicator: "orange"
                        });
                        frm.set_value("first_name", "");
                        frm.set_value("last_name", "");
                    }
                }
            });
        } else {
            frm.set_value("first_name", "");
            frm.set_value("last_name", "");
        }
    }
});
