frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        if (!frm.doc.custom_contact_id && frm.doc.customer && frm.doc.contact_person) {
            frm.add_custom_button(__('Update Contact'), function () {
                if (frm.doc.customer && frm.doc.contact_person) {
                    frappe.call({
                        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.fetch_xero_contacts',
                        args: {
                            contact_person: frm.doc.contact_person
                        },
                        callback: function (r) {
                            if (r.message && r.message.length > 0) {
                                show_contact_mapping_dialog(frm, r.message, frm.doc.contact_person);
                            } else {
                                show_create_contact_dialog(frm, frm.doc.contact_person);
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

function show_contact_mapping_dialog(frm, xero_contacts, contact_person) {
    let d = new frappe.ui.Dialog({
        title: __('Map Contact to Xero'),
        fields: [
            {
                fieldname: 'contact_person',
                fieldtype: 'Data',
                label: __('Contact Person'),
                default: contact_person,
                read_only: 1
            },
            {
                fieldname: 'xero_contacts',
                fieldtype: 'HTML',
                label: __('Similar Xero Contacts')
            }
        ],
        primary_action_label: __('Close'),
        primary_action: function() {
            d.hide();
        }
    });

    let html = '<div style="max-height: 300px; overflow-y: auto;">';
    xero_contacts.forEach(function(contact) {
        html += `
            <div style="border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 4px;">
                <div><strong>${contact.Name || ''}</strong></div>
                <div>Email: ${contact.EmailAddress || 'N/A'}</div>
                <div>Phone: ${contact.Phones && contact.Phones[0] ? contact.Phones[0].PhoneNumber : 'N/A'}</div>
                <button class="btn btn-primary btn-sm" 
                        onclick="map_contact('${contact.ContactID}', '${frm.doc.contact_person}', '${frm.doc.name}')"
                        style="margin-top: 5px;">
                    Map Contact
                </button>
            </div>
        `;
    });
    html += '</div>';

    d.fields_dict.xero_contacts.$wrapper.html(html);
    d.show();
}

function map_contact(contact_id, contact_person, sales_invoice) {
    frappe.call({
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.map_contact_to_xero',
        args: {
            contact_id: contact_id,
            contact_person: contact_person,
            sales_invoice: sales_invoice
        },
        callback: function(r) {
            if (r.message) {
                frappe.msgprint(__('Contact mapped successfully'));
                cur_frm.reload_doc();
            } else {
                frappe.msgprint(__('Failed to map contact'));
            }
        }
    });
}

function show_create_contact_dialog(frm, contact_person) {
    let d = new frappe.ui.Dialog({
        title: __('Create Contact in Xero'),
        fields: [
            {
                fieldname: 'message',
                fieldtype: 'HTML',
                label: __('Message')
            }
        ],
        primary_action_label: __('Create Contact'),
        primary_action: function() {
            create_contact_in_xero(frm, contact_person);
            d.hide();
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() {
            d.hide();
        }
    });

    let html = `
        <div style="padding: 10px;">
            <p><strong>No similar contacts found in Xero for:</strong> ${contact_person}</p>
            <p>Would you like to create a new contact in Xero using the details from ERPNext?</p>
        </div>
    `;

    d.fields_dict.message.$wrapper.html(html);
    d.show();
}

function create_contact_in_xero(frm, contact_person) {
    frappe.call({
        method: 'xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice.create_contact_and_map',
        args: {
            contact_person: contact_person,
            sales_invoice: frm.doc.name
        },
        callback: function(r) {
            if (r.message && r.message.status === 'success') {
                frappe.msgprint(__('Contact created successfully in Xero'));
                cur_frm.reload_doc();
            } else {
                frappe.msgprint(__('Failed to create contact in Xero'));
            }
        }
    });
}
