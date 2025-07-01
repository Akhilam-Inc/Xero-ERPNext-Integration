
frappe.ui.form.on('Contact', {
    refresh(frm) {
        // Make the send_to_xero field read-only if contact already exists in Xero
        if (frm.doc.custom_contact_id) {
            frm.set_df_property("custom_send_to_xero", 'read_only', 1);
        }
    },
    
    custom_send_to_xero: function(frm) {
        // Validate account number when checkbox is checked
        if (frm.doc.custom_send_to_xero && !frm.doc.custom_account_number) {
            frappe.show_alert({
                title: 'Warning',
                message: 'Please enter account number before enabling Xero sync',
                indicator: 'orange'
            });
        }
    }
});
