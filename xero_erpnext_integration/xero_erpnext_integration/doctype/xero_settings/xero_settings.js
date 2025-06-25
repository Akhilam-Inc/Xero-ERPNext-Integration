// Copyright (c) 2025, nasirucode and contributors
// For license information, please see license.txt

frappe.ui.form.on("Xero Settings", {
	refresh(frm) {

	},
    before_save: function(frm) {
		if (frm.doc.enable) {
			frappe.call({
				method: "xero_erpnext_integration.xero_erpnext_integration.apis.connection.test_connection",
				freeze: true,
				callback: function(r) {
					if (r.message.status === "success") {
						frappe.show_alert({
							title: __('Success'),
							indicator: 'green',
							message: __('xero connection is successfully authorized')
						}, 10);
                        // frm.save()
					} else {
						frm.set_value('enable', 0);
						frappe.show_alert({
							title: __('Connection Failed'),
							indicator: 'red',
							message: __(r.message.message || 'Invalid API Credentials')
						}, 10);
					}
				},
				error: function(r) {
					frm.set_value('enable', 0);
					frappe.show_alert({
						title: __('Error'),
						indicator: 'red',
						message: __('xero API Connection Failed. Please check your credentials.')
					}, 10);
				}
			});
		}
	},
});
