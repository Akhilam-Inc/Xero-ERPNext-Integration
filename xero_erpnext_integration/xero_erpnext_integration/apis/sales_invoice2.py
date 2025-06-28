import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate
from .base import get_xero_client
import json

class XeroSalesInvoiceSync:
    """Sync Sales Invoices between ERPNext and Xero"""
    
    def __init__(self):
        self.xero_client = get_xero_client()
        self.settings = frappe.get_single("Xero Settings")
    
    def sync_invoice_to_xero(self, sales_invoice_name):
        """Sync ERPNext Sales Invoice to Xero"""
        try:
            # Get Sales Invoice
            sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
            
            if sales_invoice.docstatus != 1:
                return {"status": "error", "message": "Only submitted invoices can be synced"}
            
            # Check if already synced
            if sales_invoice.get("custom_xero_invoice_id"):
                return {"status": "error", "message": "Invoice already synced to Xero"}
            
            # Prepare customer (contact)
            contact_id = self._sync_customer_to_xero(sales_invoice.customer)
            if not contact_id:
                return {"status": "error", "message": "Failed to sync customer to Xero"}
            
            # Prepare invoice data
            invoice_data = self._prepare_invoice_data(sales_invoice, contact_id)
            
            # Create invoice in Xero
            xero_invoice = self.xero_client.create_invoice(invoice_data)
            
            if xero_invoice:
                # Update Sales Invoice with Xero details
                sales_invoice.custom_xero_invoice_id = xero_invoice.get("InvoiceID")
                sales_invoice.custom_xero_invoice_number = xero_invoice.get("InvoiceNumber")
                sales_invoice.custom_xero_sync_status = "Synced"
                sales_invoice.custom_xero_sync_date = nowdate()
                sales_invoice.save(ignore_permissions=True)
                
                return {
                    "status": "success",
                    "message": "Invoice synced successfully",
                    "xero_invoice_id": xero_invoice.get("InvoiceID"),
                    "xero_invoice_number": xero_invoice.get("InvoiceNumber")
                }
            else:
                return {"status": "error", "message": "Failed to create invoice in Xero"}
                
        except Exception as e:
            error_msg = f"Failed to sync invoice: {str(e)}"
            frappe.log_error(error_msg, "Xero Invoice Sync")
            return {"status": "error", "message": error_msg}
    
    def _sync_customer_to_xero(self, customer_name):
        """Sync customer to Xero and return contact ID"""
        try:
            # Get customer details
            customer = frappe.get_doc("Customer", customer_name)
            
            # Check if customer already exists in Xero
            existing_contacts = self.xero_client.get_contacts(customer.customer_name)
            
            if existing_contacts:
                return existing_contacts[0].get("ContactID")
            
            # Create new contact in Xero
            contact_data = {
                "Name": customer.customer_name,
                "EmailAddress": customer.email_id or "",
                "ContactStatus": "ACTIVE"
            }
            
            # Add address if available
            if customer.customer_primary_address:
                address = frappe.get_doc("Address", customer.customer_primary_address)
                contact_data["Addresses"] = [{
                    "AddressType": "STREET",
                    "AddressLine1": address.address_line1 or "",
                    "AddressLine2": address.address_line2 or "",
                    "City": address.city or "",
                    "Region": address.state or "",
                    "PostalCode": address.pincode or "",
                    "Country": address.country or ""
                }]
            
            # Add phone if available
            if customer.mobile_no:
                contact_data["Phones"] = [{
                    "PhoneType": "MOBILE",
                    "PhoneNumber": customer.mobile_no
                }]
            
            xero_contact = self.xero_client.create_contact(contact_data)
            
            if xero_contact:
                # Update customer with Xero contact ID
                customer.custom_xero_contact_id = xero_contact.get("ContactID")
                customer.save(ignore_permissions=True)
                return xero_contact.get("ContactID")
            
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to sync customer: {str(e)}", "Xero Customer Sync")
            return None
    
    def _prepare_invoice_data(self, sales_invoice, contact_id):
        """Prepare invoice data for Xero API"""
        try:
            # Prepare line items
            line_items = []
            for item in sales_invoice.items:
                line_item = {
                    "Description": item.description or item.item_name,
                    "Quantity": flt(item.qty),
                    "UnitAmount": flt(item.rate),
                    "AccountCode": self._get_account_code(item.income_account),
                    "TaxType": self._get_tax_type(item.item_tax_template)
                }
                line_items.append(line_item)
            
            # Prepare invoice data
            invoice_data = {
                "Type": "ACCREC",  # Accounts Receivable
                "Contact": {
                    "ContactID": contact_id
                },
                "Date": getdate(sales_invoice.posting_date).strftime("%Y-%m-%d"),
                "DueDate": getdate(sales_invoice.due_date).strftime("%Y-%m-%d") if sales_invoice.due_date else None,
                "LineItems": line_items,
                "Reference": sales_invoice.name,
                "Status": "AUTHORISED"
            }
            
            # Add currency if not base currency
            if sales_invoice.currency != frappe.get_cached_value("Company", sales_invoice.company, "default_currency"):
                invoice_data["CurrencyCode"] = sales_invoice.currency
                invoice_data["CurrencyRate"] = flt(sales_invoice.conversion_rate)
            
            return invoice_data
            
        except Exception as e:
            frappe.log_error(f"Failed to prepare invoice data: {str(e)}", "Xero Invoice Data")
            raise
    
    def _get_account_code(self, account_name):
        """Get Xero account code for ERPNext account"""
        try:
            # Try to get mapped account code
            account = frappe.get_doc("Account", account_name)
            if hasattr(account, 'custom_xero_account_code') and account.custom_xero_account_code:
                return account.custom_xero_account_code
            
            # Default account codes based on account type
            account_type_mapping = {
                "Income Account": "200",  # Sales
                "Stock": "310",  # Cost of Goods Sold
                "Expense Account": "400"  # General Expenses
            }
            
            return account_type_mapping.get(account.account_type, "200")
            
        except Exception:
            return "200"  # Default to Sales account
    
    def _get_tax_type(self, tax_template):
        """Get Xero tax type for ERPNext tax template"""
        try:
            if not tax_template:
                return "NONE"
            
            # Map common tax templates to Xero tax types
            tax_mapping = {
                "GST 10%": "OUTPUT2",
                "VAT 20%": "OUTPUT",
                "Sales Tax": "OUTPUT"
            }
            
            return tax_mapping.get(tax_template, "NONE")
            
        except Exception:
            return "NONE"


# API Methods
@frappe.whitelist()
def sync_invoice_to_xero(sales_invoice_name):
    """API method to sync Sales Invoice to Xero"""
    try:
        sync_handler = XeroSalesInvoiceSync()
        return sync_handler.sync_invoice_to_xero(sales_invoice_name)
    except Exception as e:
        frappe.log_error(f"API sync invoice failed: {str(e)}", "Xero Invoice Sync API")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def bulk_sync_invoices(invoice_names):
    """Bulk sync multiple invoices to Xero"""
    try:
        if isinstance(invoice_names, str):
            invoice_names = json.loads(invoice_names)
        
        sync_handler = XeroSalesInvoiceSync()
        results = []
        
        for invoice_name in invoice_names:
            result = sync_handler.sync_invoice_to_xero(invoice_name)
            result["invoice"] = invoice_name
            results.append(result)
        
        return {
            "status": "completed",
            "total": len(results),
            "successful": len([r for r in results if r.get("status") == "success"]),
            "failed": len([r for r in results if r.get("status") == "error"]),
            "results": results
        }
        
    except Exception as e:
        frappe.log_error(f"Bulk sync failed: {str(e)}", "Xero Bulk Sync")
        return {"status": "error", "message": str(e)}


# Auto-sync hook for Sales Invoice
def auto_sync_sales_invoice(doc, method):
    """Auto-sync Sales Invoice to Xero on submit"""
    try:
        settings = frappe.get_single("Xero Settings")
        
        if not settings.enable or not settings.auto_sync_invoices:
            return
        
        # Enqueue sync to avoid blocking the submit process
        frappe.enqueue(
            "xero_erpnext_integration.apis.sales_invoice.sync_invoice_to_xero",
            sales_invoice_name=doc.name,
            queue="default",
            timeout=300
        )
        
    except Exception as e:
        frappe.log_error(f"Auto-sync failed: {str(e)}", "Xero Auto Sync")
