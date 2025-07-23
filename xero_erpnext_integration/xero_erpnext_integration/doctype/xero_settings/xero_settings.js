frappe.ui.form.on('Xero Settings', {
    refresh: function(frm) {
        // Handle authorization callback
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        
        // Always process new authorization codes from URL
        if (code && code !== frm.doc.code) {
            handle_authorization_callback(frm, code, urlParams.get('scope'));
            return;
        }

        // Add custom buttons
        frm.add_custom_button(__('Authorize'), function() {
            authorize(frm);
        });

        frm.add_custom_button(__('Sync Paid Invoices'), function() {
            sync_paid_invoices(frm);
        });
        
        // Show connection status
        if (frm.doc.access_token) {
            frm.dashboard.add_indicator(__('Connected'), 'green');
        } else {
            frm.dashboard.add_indicator(__('Not Connected'), 'red');
        }
    },

    before_save: function(frm) {
        // Process authorization if code and scope are present
        if (frm.doc.code && frm.doc.scope) {

            // Prevent multiple authorization attempts
            if (frm._authorizing) {
                return Promise.resolve();
            }
            frm._authorizing = true;
            
            return new Promise(function(resolve, reject) {
                frappe.call({
                    method: 'xero_erpnext_integration.xero_erpnext_integration.apis.connection.authorize',
                    callback: function(r) {
                        frm._authorizing = false;
                        
                        if (r.message && r.message.status === 'success') {
                            frappe.show_alert({
                                message: __('Authorization Successful!'),
                                indicator: 'green'
                            });
                            
                            // Clean up URL parameters
                            window.history.replaceState({}, document.title, window.location.pathname);
                            
                            // Refresh page if requested by backend
                            if (r.message.refresh_page) {
                                setTimeout(function() {
                                    window.location.reload();
                                }, 1500);
                            }
                            
                            resolve();
                        } else {
                            frappe.msgprint({
                                title: __('Authorization Failed'),
                                message: r.message ? r.message.message : 'Authorization failed. Please try authorizing again.',
                                indicator: 'red'
                            });
                            resolve();
                        }
                    },
                    error: function(r) {
                        frm._authorizing = false;
                        
                        frappe.msgprint({
                            title: __('Authorization Error'),
                            message: __('Network error during authorization. Please try again.'),
                            indicator: 'red'
                        });
                        resolve();
                    }
                });
            });
        }
    }
});

function handle_authorization_callback(frm, code, scope) {
    // Set the authorization values and save to trigger before_save
    frm.set_value("code", code);
    frm.set_value("scope", scope);
    frm.save();
}

function sync_paid_invoices(frm) {
    frappe.call({
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.sync_invoice_payments',
        callback: function(r) {
            if (r.message && r.message.status === 'success') {
                frappe.show_alert({
                    message: __('Paid Invoices Synced Successfully'),
                    indicator: 'green'
                });
            } else {
                frappe.show_alert({
                    message: __('Error Syncing Paid Invoices'),
                    indicator: 'red'
                });
            }
        }
    });
}

function authorize(frm) {
    // Validate required fields
    if (!frm.doc.client_id) {
        frappe.msgprint(__('Please enter the Client ID before authorizing.'));
        return;
    }
    
    if (!frm.doc.redirect_uri) {
        frappe.msgprint(__('Please enter the Redirect URI before authorizing.'));
        return;
    }
    
    // Generate state if not exists
    const state = frm.doc.state || Math.random().toString(36).substring(2, 15);
    if (!frm.doc.state) {
        frm.set_value('state', state);
    }
    
    // Build authorization URL
    const authUrl = 'https://login.xero.com/identity/connect/authorize?' + 
        new URLSearchParams({
            response_type: 'code',
            client_id: frm.doc.client_id,
            redirect_uri: frm.doc.redirect_uri,
            scope: frm.doc.scope || 'openid profile email accounting.transactions offline_access accounting.contacts',
            state: state
        }).toString();
    
    // Open authorization window
    window.open(authUrl, '_blank', 'width=600,height=700,scrollbars=yes,resizable=yes');
    
    frappe.show_alert({
        message: __('Complete the authorization in the opened window'),
        indicator: 'blue'
    });
}
