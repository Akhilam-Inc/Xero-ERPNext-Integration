frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        if (!frm.doc.custom_contact_id && frm.doc.customer) {
            frm.add_custom_button(__('Update Contact'), function () {
                if (frm.doc.customer) {
                    frappe.call({
                        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.get_customer_contact_id',
                        args: {
                            customer: frm.doc.customer
                        },
                        callback: function (r) {
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

            });
        }
    },
    before_submit: async function (frm) {

        return new Promise(function (resolve, reject) {
            frappe.dom.unfreeze();
            if (frm.doc.custom_contact_id) {
                resolve();
            } else {
                let message = `Please confirm before submiting:<br><br>
                Xero Contact Id is not found for this customer: ${frm.doc.customer}<br>
                Do you still want to proceed without syncing invouce to Xero?<br><br>`;
                frappe.confirm(
                    message,
                    () => {
                        // User clicked "Yes"
                        console.log("User confirmed to proceed without syncing to Xero");
                        resolve();
                    },
                    () => {
                        frappe.msgprint(`You can sync this invoice by following steps:<br><br>
                        1. Go to Contact Master and add Customer Link If missing.<br>
                        2. Click 'Sync to Zero' button in Contact.<br>
                        3. Go to Sales Invoice and click 'Update Contact' button.<br>
                        4. Click 'Submit' button in Sales Invoice.<br><br>`);
                        reject();
                    }
                );
            }
        });
    },

    customer(frm) {
        // Also trigger when customer is changed
        if (frm.doc.customer) {
            frappe.call({
                method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.get_customer_contact_id',
                args: {
                    customer: frm.doc.customer
                },
                callback: function (r) {
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
