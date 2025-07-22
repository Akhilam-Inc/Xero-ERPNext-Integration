import frappe
from frappe import _

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
