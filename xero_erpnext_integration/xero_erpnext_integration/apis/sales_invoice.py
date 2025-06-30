import frappe
from .base import get_xero_client
import json


@frappe.whitelist()
def get_specific_invoices():
    #   /invoices?Statuses=AUTHORISED,PAID&ContactIDs=3138017f-8ddc-420e-a159-e7e1cf9e643d,4b2df4a1-7aa5-4ce3-9e9c-3c55794c5283
    try:
        client = get_xero_client()
        response = client.make_request("GET", "/invoices?Statuses=PAID")
        
        return {
            "status": "success",
            "data": response.get("Invoices", [])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def get_xero_invoices():
    """Get Xero invoices"""
    try:
        client = get_xero_client()
        response = client.make_request("GET", "/Invoices")
        
        return {
            "status": "success",
            "data": response.get("Invoices", [])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def get_invoice(invoice_id):
        """Get invoice from Xero"""
        try:
            client = get_xero_client()
            response = client.make_request("GET", f"Invoices/{invoice_id}")
            
            if response and "Invoices" in response:
                return {
                    "status": "success",
                    "data": response["Invoices"][0]
                }
            
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to get invoice: {str(e)}", "Xero Get Invoice")
            return None


@frappe.whitelist() 
def create_invoice(doc, method=None):
    """Create invoice in Xero"""
    try:
        client = get_xero_client()
        
        # Get the Sales Invoice document
        if isinstance(doc, str):
            invoice = frappe.get_doc("Sales Invoice", doc)
        else:
            invoice = doc
        
        # Get customer contact ID from Xero
        contact_id = get_customer_contact_id(invoice.customer)
        if not contact_id:
            frappe.throw(f"No Xero contact ID found for customer: {invoice.customer}")
        
        # Prepare line items
        line_items = []
        for item in invoice.items:
            line_item = {
                "Description": item.description or item.item_name,
                "Quantity": str(item.qty),
                "UnitAmount": str(item.rate),
                "AccountCode": item.get("custom_account_code") or "200",  # Default to 200 if not set
            }
            
            # Add discount rate if available
            if item.get("discount_percentage"):
                line_item["DiscountRate"] = str(item.discount_percentage)
            
            line_items.append(line_item)
        
        # Prepare invoice data
        invoice_data = {
            "Type": "ACCREC",  # Accounts Receivable
            "Contact": {
                "ContactID": contact_id
            },
            "DateString": invoice.posting_date.strftime("%Y-%m-%d") if invoice.posting_date else None,
            "DueDateString": invoice.due_date.strftime("%Y-%m-%d") if invoice.due_date else None,
            "LineAmountTypes": "Exclusive",  # Tax exclusive
            "LineItems": line_items,
            "Reference": invoice.name,  # ERPNext invoice reference
            "Status": "AUTHORISED"  # Create as draft initially
        }
        
        # Add currency if different from base currency
        if invoice.currency and invoice.currency != frappe.get_cached_value("Company", invoice.company, "default_currency"):
            invoice_data["CurrencyCode"] = invoice.currency
        
        data = {"Invoices": [invoice_data]}
        response = client.make_request("POST", "/Invoices", data=data)
        
        if response and "Invoices" in response:
            xero_invoice = response["Invoices"][0]
            
            # Update ERPNext Sales Invoice with Xero Invoice ID
            # frappe.db.set_value("Sales Invoice", invoice.name, "custom_xero_invoice_number", xero_invoice.get("InvoiceID"))
            # frappe.db.commit()
            
            return {
                "status": "success",
                "data": xero_invoice,
                "message": f"Invoice created in Xero with ID: {xero_invoice.get('InvoiceID')}"
            }
        
        return {
            "status": "error",
            "message": "Failed to create invoice in Xero"
        }
        
    except Exception as e:
        frappe.log_error("Xero Create Invoice", f"Failed to create invoice in Xero: {str(e)}")
        frappe.throw(f"Failed to create invoice in Xero: {str(e)}")
        return False


@frappe.whitelist()
def get_customer_contact_id(customer):
    # Method 1: Using frappe.db.sql for more control
    try:
        dynamic_links = frappe.get_all('Dynamic Link',
            filters={
                'link_doctype': 'Customer',
                'link_name': customer,
                'parenttype': 'Contact'
            },
            fields=['parent'],
            limit=1
        )
        
        if dynamic_links:
            contact_name = dynamic_links[0].parent
            contact = frappe.get_doc('Contact', contact_name)
            return contact.get('custom_contact_id')
        
        return None
    except Exception as e:
        frappe.throw("Error getting contact id for the selected customer")
