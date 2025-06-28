import frappe
from .base3 import get_xero_client

@frappe.whitelist()
def sync_invoice_to_xero(sales_invoice_name):
    """Sync a specific invoice to Xero"""
    try:
        # Get sales invoice
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        # Check if already synced
        if getattr(sales_invoice, 'xero_invoice_id', None):
            return {
                "status": "info",
                "message": f"Invoice {sales_invoice_name} already synced to Xero"
            }
        
        # Map ERPNext invoice to Xero format
        xero_invoice_data = map_erpnext_to_xero_invoice(sales_invoice)
        
        # Send to Xero
        client = get_xero_client()
        response = client.make_request("POST", "/Invoices", data={"Invoices": [xero_invoice_data]})
        
        if response and response.get("Invoices"):
            xero_invoice = response["Invoices"][0]
            xero_invoice_id = xero_invoice.get("InvoiceID")
            
            # Update ERPNext invoice
            sales_invoice.db_set('xero_invoice_id', xero_invoice_id)
            sales_invoice.db_set('xero_synced', 1)
            
            return {
                "status": "success",
                "message": f"Invoice {sales_invoice_name} synced successfully to Xero",
                "xero_invoice_id": xero_invoice_id
            }
        else:
            return {
                "status": "error",
                "message": "No invoice data received from Xero"
            }
            
    except Exception as e:
        frappe.logger().error(f"Failed to sync invoice {sales_invoice_name}: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist()
def sync_all_pending_invoices():
    """Sync all pending invoices to Xero"""
    try:
        # Get all submitted invoices not synced to Xero
        pending_invoices = frappe.db.sql("""
            SELECT name 
            FROM `tabSales Invoice` 
            WHERE docstatus = 1 
            AND (xero_synced IS NULL OR xero_synced = 0)
            AND (xero_invoice_id IS NULL OR xero_invoice_id = '')
            ORDER BY creation DESC
            LIMIT 50
        """, as_dict=True)
        
        if not pending_invoices:
            return {
                "status": "info",
                "message": "No pending invoices found to sync"
            }
        
        success_count = 0
        error_count = 0
        errors = []
        
        for invoice in pending_invoices:
            result = sync_invoice_to_xero(invoice.name)
            
            if result["status"] == "success":
                success_count += 1
            else:
                error_count += 1
                errors.append(f"{invoice.name}: {result['message']}")
        
        message = f"Sync completed: {success_count} successful, {error_count} failed"
        if errors:
            message += f"\n\nErrors:\n" + "\n".join(errors[:5])  # Show first 5 errors
            if len(errors) > 5:
                message += f"\n... and {len(errors) - 5} more errors"
        
        return {
            "status": "success" if error_count == 0 else "warning",
            "message": message,
            "success_count": success_count,
            "error_count": error_count
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def map_erpnext_to_xero_invoice(sales_invoice):
    """Map ERPNext Sales Invoice to Xero Invoice format"""
    
    # Map line items
    line_items = []
    for item in sales_invoice.items:
        line_item = {
            "Description": item.description or item.item_name,
            "Quantity": item.qty,
            "UnitAmount": item.rate,
            "AccountCode": "200",  # Default sales account
            "TaxType": "OUTPUT2" if item.tax_rate else "NONE"
        }
        line_items.append(line_item)
    
    # Create invoice data
    invoice_data = {
        "Type": "ACCREC",  # Accounts Receivable
        "Contact": {
            "Name": sales_invoice.customer_name or sales_invoice.customer
        },
        "Date": str(sales_invoice.posting_date),
        "DueDate": str(sales_invoice.due_date) if sales_invoice.due_date else str(sales_invoice.posting_date),
        "LineItems": line_items,
        "InvoiceNumber": sales_invoice.name,
        "Reference": sales_invoice.po_no or sales_invoice.name,
        "Status": "AUTHORISED"
    }
    
    return invoice_data

@frappe.whitelist()
def create_payment_from_xero(xero_invoice_id, payment_amount):
    """Create payment entry when payment is received in Xero"""
    try:
        # Find ERPNext invoice
        sales_invoice_name = frappe.db.get_value(
            "Sales Invoice", 
            {"xero_invoice_id": xero_invoice_id}, 
            "name"
        )
        
        if not sales_invoice_name:
            return {
                "status": "error",
                "message": f"No ERPNext invoice found for Xero ID: {xero_invoice_id}"
            }
        
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        # Check if already paid
        if sales_invoice.status == "Paid":
            return {
                "status": "info",
                "message": f"Invoice {sales_invoice_name} already marked as paid"
            }
        
        # Create Payment Entry
        payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": sales_invoice.customer,
            "paid_amount": payment_amount,
            "received_amount": payment_amount,
            "target_exchange_rate": 1,
            "reference_no": f"Xero-{xero_invoice_id}",
            "reference_date": frappe.utils.today(),
            "paid_to": get_default_receivable_account(),
            "paid_from": get_default_cash_account(),
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice_name,
                "allocated_amount": payment_amount
            }]
        })
        
        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()
        
        return {
            "status": "success",
            "message": f"Payment entry created: {payment_entry.name}",
            "payment_entry": payment_entry.name
        }
        
    except Exception as e:
        frappe.logger().error(f"Failed to create payment for Xero invoice {xero_invoice_id}: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

def get_default_receivable_account():
    """Get default receivable account"""
    company = frappe.defaults.get_user_default("Company")
    return frappe.db.get_value("Company", company, "default_receivable_account")

def get_default_cash_account():
    """Get default cash account"""  
    company = frappe.defaults.get_user_default("Company")
    return frappe.db.get_value("Company", company, "default_cash_account")


