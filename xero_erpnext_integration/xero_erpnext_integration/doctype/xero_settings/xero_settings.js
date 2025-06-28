frappe.ui.form.on('Xero Settings', {
    refresh: function(frm) {
		const urlParams = new URLSearchParams(window.location.search);
		const code = urlParams.get('code');
		if (code) {
            console.log(code)
			frm.set_value("code", code)
            frm.set_value("scope", urlParams.get('scope'))
			frm.save()
		}
        // Add custom buttons
        
        frm.add_custom_button(__('Authorize'), function() {
            authorize(frm);
        });
        
        frm.add_custom_button(__('Get Invoices'), function() {
            frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.get_xero_invoices',
                callback: function(r) {
                    if (r.message) {
                        if (r.message.status === 'success') {
                           console.log(r.message)
                        } else {
                            console.log(r)
                        }
                    }
                }
            });
        });

        frm.add_custom_button(__('Get Contacts'), function() {
            frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.get_xero_contacts',
                callback: function(r) {
                    if (r.message) {
                        if (r.message.status === 'success') {
                           console.log(r.message)
                        } else {
                            console.log(r)
                        }
                    }
                }
            });
        });
        
        // Show connection status
        if (frm.doc.access_token) {
            frm.dashboard.add_indicator(__('Connected'), 'green');
        } else {
            frm.dashboard.add_indicator(__('Not Connected'), 'red');
        }
    },
	before_save: function(frm) {
		// if(frm.doc.enable){
		// 	test_xero_connection(frm);
		// }
		// else{
		// 	frappe.show_alert("Please enable the integration to test the connection.");
		// }

        if(frm.doc.code && frm.doc.scope){
            frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.authorize',
                callback: function(r) {
                    if (r.message) {
                        if (r.message.status === 'success') {
                            // window.location.reload()
                            frappe.msgprint({
                                title: __('Connection Successful'),
                                message: r.message.message,
                                indicator: 'green'
                            });
                            frm.set_value("enable", 1)
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
		
	}
});

function test_xero_connection(frm) {
    frappe.call({
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.test_xero_connection',
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
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.get_organisation_details',
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
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.invoice_sync.sync_all_pending_invoices',
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

function authorize(frm) {
    // Check if required fields are filled
    if (!frm.doc.client_id) {
        frappe.msgprint({
            title: __('Missing Client ID'),
            message: __('Please enter the Client ID before authorizing.'),
            indicator: 'red'
        });
        return;
    }
    
    if (!frm.doc.redirect_uri) {
        frappe.msgprint({
            title: __('Missing Redirect URI'),
            message: __('Please enter the Redirect URI before authorizing.'),
            indicator: 'red'
        });
        return;
    }
    
    // Build authorization URL with parameters from form
    const baseUrl = 'https://login.xero.com/identity/connect/authorize';
    const params = new URLSearchParams({
        response_type: 'code',
        client_id: frm.doc.client_id,
        redirect_uri: frm.doc.redirect_uri,
        scope: frm.doc.scope || 'openid profile email accounting.transactions',
        state: frm.doc.state || Math.random().toString(36).substring(2, 15)
    });
    
    const authUrl = `${baseUrl}?${params.toString()}`;
    
    // Save the state value to the document for verification later
    if (!frm.doc.state) {
        frm.set_value('state', params.get('state'));
    }
    
    // Open authorization URL in new window/tab
    window.open(authUrl, '_blank', 'width=600,height=700,scrollbars=yes,resizable=yes');
    
    frappe.show_alert({
        message: __('Authorization window opened. Please complete the authorization process.'),
        indicator: 'blue'
    });
}

