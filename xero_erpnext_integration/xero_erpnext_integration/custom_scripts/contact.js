frappe.ui.form.on('Contact', {
    refresh(frm) {
        console.log("I am here")
    },
    before_save: function(frm) {
        frappe.call({
            method: 'xero_erpnext_integration.xero_erpnext_integration.apis.contact.create_contact',
            args:{
                doc: frm.doc
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
    }
})