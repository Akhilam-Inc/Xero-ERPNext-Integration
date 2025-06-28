frappe.ui.form.on('Contact', {
    refresh(frm) {
        console.log("I am here")
    },
    before_save: function(frm) {
        if(frm.doc.custom_send_to_xero){
            if(frm.doc.custom_account_number){
                frappe.call({
                    method: 'xero_erpnext_integration.xero_erpnext_integration.apis.contact.create_contact',
                    args:{
                        doc: frm.doc.name
                    },
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
            }else{
                frappe.show_alert({
                    title: 'Error',
                    message: 'Please enter account number to create contact in Xero',
                    indicator: 'red'
                })
            }
        }
        
    }
})