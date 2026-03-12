frappe.ui.form.on('Member', {
    refresh: function(frm) {
        frm.trigger('set_designated_representative_query');

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

    set_designated_representative_query: function(frm) {
        frm.set_query('designated_representative', function() {
            if (!frm.doc.customer) {
                return { filters: { name: '' } };
            }

            return {
                query: 'frappe.contacts.doctype.contact.contact.contact_query',
                filters: {
                    link_doctype: 'Customer',
                    link_name: frm.doc.customer,
                },
            };
        });
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
        frm.trigger('set_designated_representative_query');

        if (frm.doc.designated_representative) {
            frm.set_value('designated_representative', '');
        }

        frm.trigger('refresh_member_name');
    },

    designated_representative: function(frm) {
        frm.trigger('refresh_member_name');
    },

    refresh_member_name: function(frm) {
        if (frm.doc.customer) {
            frm.call("get_contact_details").then(r => {
                if (r.message) {
                    frm.set_value('member_name', r.message.member_name || '');
                }
            });
        } else {
            frm.set_value('member_name', '');
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
