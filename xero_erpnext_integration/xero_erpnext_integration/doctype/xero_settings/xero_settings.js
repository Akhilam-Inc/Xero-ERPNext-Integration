frappe.ui.form.on('Xero Settings', {
    refresh: function(frm) {
        // Add custom buttons
        
        frm.add_custom_button(__('Get Organisation Info'), function() {
            get_organisation_info(frm);
        });
        
        frm.add_custom_button(__('Sync Pending Invoices'), function() {
            sync_pending_invoices(frm);
        });
        
        // Show connection status
        if (frm.doc.access_token && frm.doc.tenant_id) {
            frm.dashboard.add_indicator(__('Connected'), 'green');
        } else {
            frm.dashboard.add_indicator(__('Not Connected'), 'red');
        }
    },
	before_save: function(frm) {
		if(frm.doc.enable){
			test_xero_connection(frm);
		}
		else{
			frappe.show_alert("Please enable the integration to test the connection.");
		}
		
	}
});

function test_xero_connection(frm) {
    frappe.call({
        method: 'xero_erpnext_integration.apis.connection.test_xero_connection',
        callback: function(r) {
            if (r.message) {
                if (r.message.status === 'success') {
                    frappe.msgprint({
                        title: __('Connection Successful'),
                        message: r.message.message,
                        indicator: 'green'
                    });
                } else {
					frm.set_value("enable", 0)
                    frappe.msgprint({
                        title: __('Connection Failed'),
                        message: r.message.message,
                        indicator: 'red'
                    });
                }
            }
        }
    });
}

function get_organisation_info(frm) {
    frappe.call({
        method: 'xero_erpnext_integration.apis.connection.get_organisation_details',
        callback: function(r) {
            if (r.message && r.message.status === 'success') {
                let org = r.message.data;
                let msg = `
                    <b>Organisation:</b> ${org.Name}<br>
                    <b>Country:</b> ${org.CountryCode}<br>
                    <b>Currency:</b> ${org.BaseCurrency}<br>
                    <b>Financial Year End:</b> ${org.FinancialYearEndDay}/${org.FinancialYearEndMonth}<br>
                    <b>Tax Number:</b> ${org.TaxNumber || 'Not set'}
                `;
                
                frappe.msgprint({
                    title: __('Organisation Information'),
                    message: msg,
                    indicator: 'blue'
                });
            } else {
                frappe.msgprint({
                    title: __('Error'),
                    message: r.message ? r.message.message : 'Failed to get organisation info',
                    indicator: 'red'
                });
            }
        }
    });
}

function sync_pending_invoices(frm) {
    frappe.confirm(
        'This will sync all pending invoices to Xero. Continue?',
        function() {
            frappe.call({
                method: 'xero_erpnext_integration.apis.invoice_sync.sync_all_pending_invoices',
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('Sync Result'),
                            message: r.message.message,
                            indicator: r.message.status === 'success' ? 'green' : 'orange'
                        });
                    }
                }
            });
        }
    );
}
