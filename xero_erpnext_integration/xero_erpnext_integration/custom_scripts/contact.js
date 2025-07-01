// frappe.ui.form.on('Contact', {
//     refresh(frm) {
//         console.log("I am here")
//     },
//     before_save: function(frm) {
//         if(frm.doc.custom_send_to_xero){
//             if(frm.doc.custom_account_number){
//                 frappe.call({
//                     method: 'xero_erpnext_integration.xero_erpnext_integration.apis.contact.create_contact',
//                     args:{
//                         doc: frm.doc.name
//                     },
//                     callback: function(r) {
//                         if (r.message) {
//                             if (r.message.status === 'success') {
                                
//                                 frappe.show_alert({
//                                     title: 'Success',
//                                     message: 'Contact created successfully in Xero',
//                                     indicator: 'green'
//                                 })
//                                 frm.set_value("custom_contact_id", r.message.data[0].ContactID);
//                                 frm.set_df_property("custom_send_to_xero", 'read_only', 1);
//                                 // frm.save()
//                             } else {
//                                 frappe.show_alert({
//                                     title: 'Error',
//                                     message: 'Error creating contact in Xero',
//                                     indicator: 'red'
//                                 })
//                             }
//                         }
//                     }
//                 });
//             }else{
//                 frappe.show_alert({
//                     title: 'Error',
//                     message: 'Please enter account number to create contact in Xero',
//                     indicator: 'red'
//                 })
//             }
//         }
        
//     }
// })

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
