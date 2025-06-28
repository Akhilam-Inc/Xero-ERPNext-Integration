frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        console.log("I am here")
    },
    before_submit: function(frm){
        send_invoice_to_xero(frm)
    },
    before_save(frm) {
        if (frm.doc.customer) {
            // Get contact linked to the customer
            frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.get_customer_contact_id',
                args: {
                    customer: frm.doc.customer
                },
                callback: function(r) {
                    if (r.message) {
                        let contact = r.message;
                        // if (contact.custom_contact_id) {
                            // Set the custom_contact_id field in Sales Invoice
                            frm.set_value('custom_contact_id', r.message);
                            console.log('Set custom_contact_id:', r.message);
                        // }
                    }
                }
            });
        }
    },
    
    customer(frm) {
        // Also trigger when customer is changed
        if (frm.doc.customer) {
             frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.get_customer_contact_id',
                args: {
                    customer: frm.doc.customer
                },
                callback: function(r) {
                    if (r.message) {
                        let contact = r.message;
                        // if (contact.custom_contact_id) {
                            // Set the custom_contact_id field in Sales Invoice
                            frm.set_value('custom_contact_id', r.message);
                            console.log('Set custom_contact_id:', r.message);
                        // }
                    }
                }
            });
        } else {
            // Clear the field if no customer selected
            frm.set_value('custom_contact_id', '');
        }
    }
});


function send_invoice_to_xero(frm){
     frappe.call({
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.create_invoice',
        args:{
            doc: frm.doc.name
        },
        callback: function(r) {
            if (r.message) {
                if (r.message.status === 'success') {
                    console.log(r.message)
                    
                    frappe.show_alert({
                        title: 'Success',
                        message: 'Invoice created successfully in Xero',
                        indicator: 'green'
                    })
                    // frm.set_value("custom_contact_id", r.message.data[0].ContactID);
                    // frm.set_df_property("custom_send_to_xero", 'read_only', 1);
                    // frm.save()
                } else {
                    frappe.show_alert({
                        title: 'Error',
                        message: 'Error creating contact in Xero',
                        indicator: 'red'
                    })
                }
            }
        }
    });
}
