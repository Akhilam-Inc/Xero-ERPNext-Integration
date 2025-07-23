import frappe
from frappe import _

def before_submit(doc, method=None):
    """Validate before submitting Sales Invoice"""
    # If contact ID exists, allow submission
    if doc.custom_contact_id:
        return
    
    # If do not sync to xero is checked, allow submission
    if doc.custom_do_not_sync_to_xero:
        return
    
    # If no contact ID and sync is required, throw validation error
    if doc.customer and doc.contact_person and not doc.custom_contact_id and not doc.custom_do_not_sync_to_xero:
        frappe.throw(_(
            "Xero Contact ID is not found for this customer: {0}<br><br>"
            "Please follow these steps:<br>"
            "1. Click on update contact to get contact id."
        ))
    elif not doc.customer and not doc.contact_person and not doc.custom_do_not_sync_to_xero:
        frappe.throw(_(
            "Customer and Contact Person are required for Xero integration.<br>"
            "Please set Customer and Contact Person or check 'Do not Sync to Xero' to proceed."
        ))

def on_submit(doc, method=None):
    from xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice import create_invoice

    invoice_data = create_invoice(doc.name)
    if invoice_data:
        frappe.db.set_value("Sales Invoice", doc.name, "custom_xero_invoice_number", invoice_data.get("data").get("InvoiceID"))
        doc.reload()
        frappe.msgprint(
            _("Invoice created successfully in Xero"),
            title=_("Success"),
            indicator="green"
        )
    else:
        frappe.throw(_("Error creating invoice in Xero"))


def on_cancel(doc, method=None):
    """Cancel invoice in Xero when cancelled in ERPNext"""
    # Skip if no Xero integration or invoice not synced
    if not doc.custom_xero_invoice_number or doc.custom_do_not_sync_to_xero:
        return
    
    try:
        from xero_erpnext_integration.xero_erpnext_integration.apis.sales_invoice import cancel_invoice_in_xero
        
        result = cancel_invoice_in_xero(doc.custom_xero_invoice_number)
        if result and result.get("status") == "success":
            frappe.msgprint(
                _("Invoice cancelled successfully in Xero"),
                title=_("Success"),
                indicator="green"
            )
        else:
            frappe.log_error(
                f"Failed to cancel invoice {doc.name} in Xero: {result.get('message') if result else 'Unknown error'}",
                "Xero Cancel Invoice"
            )
            frappe.msgprint(
                _("Warning: Invoice was cancelled in ERPNext but could not be cancelled in Xero. Please check Error Log."),
                title=_("Warning"),
                indicator="orange"
            )
    except Exception as e:
        frappe.log_error(f"Error cancelling invoice {doc.name} in Xero: {str(e)}", "Xero Cancel Invoice")
        frappe.msgprint(
            _("Warning: Invoice was cancelled in ERPNext but could not be cancelled in Xero. Please check Error Log."),
            title=_("Warning"),
            indicator="orange"
        )
