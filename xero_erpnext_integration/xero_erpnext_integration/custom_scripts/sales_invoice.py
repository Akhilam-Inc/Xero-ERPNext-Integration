import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, cstr
from xero_erpnext_integration.apis.base import get_xero_client
from xero_python.accounting.model.contact import Contact
from xero_python.accounting.model.invoice import Invoice
from xero_python.accounting.model.line_item import LineItem
from xero_python.accounting.model.address import Address
from xero_python.accounting.model.phone import Phone
import json

class XeroSalesInvoiceSync:
    """
    Handle Sales Invoice synchronization between ERPNext and Xero
    """
    
    def __init__(self):
        self.xero_client = get_xero_client()
        self.settings = frappe.get_single("Xero Settings")
    
    def push_invoice_to_xero(self, sales_invoice_name):
        """
        Push ERPNext Sales Invoice to Xero
        Called on Sales Invoice submit
        """
        try:
            # Get Sales Invoice document
            sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
            
            # Check if already synced
            if sales_invoice.custom_xero_invoice_id:
                frappe.msgprint(_("Invoice already synced to Xero"))
                return
            
            # Validate invoice data
            self._validate_invoice_data(sales_invoice)
            
            # Get or create customer in Xero
            xero_contact = self._get_or_create_customer(sales_invoice.customer)
            
            if not xero_contact:
                frappe.throw(_("Failed to create/find customer in Xero"))
            
            # Prepare invoice data for Xero
            invoice_data = self._prepare_invoice_data(sales_invoice, xero_contact)
            
            # Create invoice in Xero
            xero_invoice = self.xero_client.create_invoice(invoice_data)
            
            if xero_invoice:
                # Update ERPNext Sales Invoice with Xero details
                sales_invoice.db_set("custom_xero_invoice_id", xero_invoice.invoice_id)
                sales_invoice.db_set("custom_xero_invoice_number", xero_invoice.invoice_number)
                sales_invoice.db_set("custom_xero_sync_status", "Synced")
                sales_invoice.db_set("custom_xero_sync_date", nowdate())
                
                frappe.msgprint(_("Invoice successfully pushed to Xero"))
                
                return {
                    "status": "success",
                    "xero_invoice_id": xero_invoice.invoice_id,
                    "xero_invoice_number": xero_invoice.invoice_number
                }
            
        except Exception as e:
            # Update sync status to failed
            frappe.db.set_value("Sales Invoice", sales_invoice_name, "custom_xero_sync_status", "Failed")
            frappe.db.set_value("Sales Invoice", sales_invoice_name, "custom_xero_sync_error", str(e))
            
            frappe.log_error(f"Failed to push invoice {sales_invoice_name} to Xero: {str(e)}", "Xero Invoice Sync Error")
            frappe.throw(_("Failed to push invoice to Xero: {0}").format(str(e)))
    
    def _validate_invoice_data(self, sales_invoice):
        """Validate Sales Invoice data before pushing to Xero"""
        if not sales_invoice.customer:
            frappe.throw(_("Customer is required"))
        
        if not sales_invoice.items:
            frappe.throw(_("Invoice items are required"))
        
        if sales_invoice.docstatus != 1:
            frappe.throw(_("Only submitted invoices can be synced to Xero"))
    
    def _get_or_create_customer(self, customer_name):
        """Get existing customer from Xero or create new one"""
        try:
            customer = frappe.get_doc("Customer", customer_name)
            
            # Check if customer already exists in Xero
            if customer.custom_xero_contact_id:
                # Verify contact still exists in Xero
                existing_contacts = self.xero_client.get_contacts(contact_name=customer.customer_name)
                for contact in existing_contacts:
                    if contact.contact_id == customer.custom_xero_contact_id:
                        return contact
            
            # Search for existing contact by name
            existing_contacts = self.xero_client.get_contacts(contact_name=customer.customer_name)
            if existing_contacts:
                contact = existing_contacts[0]
                # Update ERPNext customer with Xero contact ID
                customer.db_set("custom_xero_contact_id", contact.contact_id)
                return contact
            
            # Create new contact in Xero
            contact_data = self._prepare_contact_data(customer)
            xero_contact = self.xero_client.create_contact(contact_data)
            
            if xero_contact:
                # Update ERPNext customer with Xero contact ID
                customer.db_set("custom_xero_contact_id", xero_contact.contact_id)
                return xero_contact
            
            return None
            
        except Exception as e:
            frappe.log_error(f"Error getting/creating customer {customer_name}: {str(e)}", "Xero Customer Sync")
            raise
    
    def _prepare_contact_data(self, customer):
        """Prepare customer data for Xero contact creation"""
        contact_data = {
            "name": customer.customer_name,
            "contact_number": customer.name,  # Use ERPNext customer ID as contact number
            "email_address": customer.email_id or "",
            "is_customer": True
        }
        
        # Add address if available
        addresses = []
        if customer.customer_primary_address:
            address_doc = frappe.get_doc("Address", customer.customer_primary_address)
            address_data = {
                "address_type": "STREET",
                "address_line1": address_doc.address_line1 or "",
                "address_line2": address_doc.address_line2 or "",
                "city": address_doc.city or "",
                "region": address_doc.state or "",
                "postal_code": address_doc.pincode or "",
                "country": address_doc.country or ""
            }
            addresses.append(address_data)
        
        if addresses:
            contact_data["addresses"] = addresses
        
        # Add phone if available
        phones = []
        if customer.mobile_no:
            phones.append({
                "phone_type": "MOBILE",
                "phone_number": customer.mobile_no
            })
        
        if phones:
            contact_data["phones"] = phones
        
        return contact_data
    
    def _prepare_invoice_data(self, sales_invoice, xero_contact):
        """Prepare Sales Invoice data for Xero"""
        # Prepare line items
        line_items = []
        for item in sales_invoice.items:
            line_item = {
                "description": item.description or item.item_name,
                "quantity": flt(item.qty),
                "unit_amount": flt(item.rate),
                "line_amount": flt(item.amount),
                "account_code": self._get_account_code(item.income_account),
                "item_code": item.item_code
            }
            
            # Add tax information if available
            if item.custom_tax_rate:
                line_item["tax_type"] = self._get_tax_type(item.custom_tax_rate)
            
            line_items.append(line_item)
        
        # Prepare invoice data
        invoice_data = {
            "type": "ACCREC",  # Accounts Receivable (Sales Invoice)
            "contact": {
                "contact_id": xero_contact.contact_id
            },
            "date": getdate(sales_invoice.posting_date).strftime("%Y-%m-%d"),
            "due_date": getdate(sales_invoice.due_date).strftime("%Y-%m-%d") if sales_invoice.due_date else None,
            "invoice_number": sales_invoice.name,
            "reference": sales_invoice.po_no or "",
            "line_items": line_items,
            "status": "AUTHORISED",  # Automatically authorize the invoice
            "currency_code": sales_invoice.currency
        }
        
        return invoice_data
    
    def _get_account_code(self, account_name):
        """Get Xero account code for ERPNext account"""
        # Try to get mapped account code from custom field or settings
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
    
    def _get_tax_type(self, tax_rate):
        """Get Xero tax type based on tax rate"""
        # Map common tax rates to Xero tax types
        # This should be configurable based on your region
        tax_mapping = {
            0: "NONE",
            10: "INPUT2",  # GST 10%
            15: "GST15",   # GST 15%
            20: "20"       # VAT 20%
        }
        
        return tax_mapping.get(flt(tax_rate), "NONE")
    
    def retry_failed_sync(self, sales_invoice_name):
        """Retry failed invoice sync"""
        try:
            sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
            
            # Reset sync status
            sales_invoice.db_set("custom_xero_sync_status", "Pending")
            sales_invoice.db_set("custom_xero_sync_error", "")
            
            # Retry sync
            return self.push_invoice_to_xero(sales_invoice_name)
            
        except Exception as e:
            frappe.log_error(f"Retry sync failed for {sales_invoice_name}: {str(e)}", "Xero Retry Sync")
            raise
    
    def bulk_sync_invoices(self, filters=None):
        """Bulk sync multiple invoices to Xero"""
        try:
            # Get invoices to sync
            invoice_filters = {
                "docstatus": 1,
                "custom_xero_sync_status": ["in", ["", "Failed"]]
            }
            
            if filters:
                invoice_filters.update(filters)
            
            invoices = frappe.get_all("Sales Invoice", 
                                    filters=invoice_filters,
                                    fields=["name", "customer", "posting_date"])
            
            results = {
                "success": [],
                "failed": []
            }
            
            for invoice in invoices:
                try:
                    result = self.push_invoice_to_xero(invoice.name)
                    if result and result.get("status") == "success":
                        results["success"].append(invoice.name)
                    else:
                        results["failed"].append(invoice.name)
                        
                except Exception as e:
                    results["failed"].append(invoice.name)
                    frappe.log_error(f"Bulk sync failed for {invoice.name}: {str(e)}", "Xero Bulk Sync")
            
            return results
            
        except Exception as e:
            frappe.log_error(f"Bulk sync process failed: {str(e)}", "Xero Bulk Sync")
            raise


# Hook functions for Sales Invoice events
def on_submit(doc, method):
    """Called when Sales Invoice is submitted"""
    try:
        settings = frappe.get_single("Xero Settings")
        
        # Check if auto-sync is enabled
        if settings.enable and settings.auto_sync_invoices:
            sync_handler = XeroSalesInvoiceSync()
            sync_handler.push_invoice_to_xero(doc.name)
            
    except Exception as e:
        # Don't block invoice submission if sync fails
        frappe.log_error(f"Auto-sync failed for invoice {doc.name}: {str(e)}", "Xero Auto Sync")
        
        # Set sync status to failed
        doc.db_set("custom_xero_sync_status", "Failed")
        doc.db_set("custom_xero_sync_error", str(e))


def on_cancel(doc, method):
    """Called when Sales Invoice is cancelled"""
    try:
        if doc.custom_xero_invoice_id:
            # Note: Xero doesn't allow deleting invoices, only voiding them
            # This would require additional implementation
            frappe.msgprint(_("Note: Invoice in Xero needs to be manually voided"))
            
    except Exception as e:
        frappe.log_error(f"Cancel sync failed for invoice {doc.name}: {str(e)}", "Xero Cancel Sync")


# API endpoints for manual sync
@frappe.whitelist()
def sync_invoice_to_xero(sales_invoice_name):
    """API endpoint to manually sync invoice to Xero"""
    try:
        sync_handler = XeroSalesInvoiceSync()
        return sync_handler.push_invoice_to_xero(sales_invoice_name)
        
    except Exception as e:
        frappe.log_error(f"Manual sync failed for {sales_invoice_name}: {str(e)}", "Xero Manual Sync")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def retry_failed_invoice_sync(sales_invoice_name):
    """API endpoint to retry failed invoice sync"""
    try:
        sync_handler = XeroSalesInvoiceSync()
        return sync_handler.retry_failed_sync(sales_invoice_name)
        
    except Exception as e:
        frappe.log_error(f"Retry sync failed for {sales_invoice_name}: {str(e)}", "Xero Retry Sync")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def bulk_sync_invoices(filters=None):
    """API endpoint for bulk invoice sync"""
    try:
        if filters and isinstance(filters, str):
            filters = json.loads(filters)
            
        sync_handler = XeroSalesInvoiceSync()
        return sync_handler.bulk_sync_invoices(filters)
        
    except Exception as e:
        frappe.log_error(f"Bulk sync failed: {str(e)}", "Xero Bulk Sync")
        return {"status": "error", "message": str(e)}
