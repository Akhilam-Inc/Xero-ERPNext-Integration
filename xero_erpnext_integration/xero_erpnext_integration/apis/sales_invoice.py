import frappe
from .base import get_xero_client
import json
import time
from datetime import datetime
from frappe.utils import today, get_datetime, flt

today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
today_ms = int(today.timestamp() * 1000)
today_date_param = f"/Date({today_ms}+0000)/"

@frappe.whitelist()
def get_specific_invoices():
    unpaid_invoices = frappe.get_all("Sales Invoice", 
        filters={
            "custom_xero_invoice_number": ["is", "set"],
            "status": ["=", "Unpaid"]
        },
        fields=["name", "customer", "grand_total", "outstanding_amount", "custom_xero_invoice_number"]
    )
    invoice_names = ",".join([invoice.custom_xero_invoice_number for invoice in unpaid_invoices]) if unpaid_invoices else ""
    
    try:
        client = get_xero_client()
        response = client.make_request("GET", f"/invoices?IDs={invoice_names}&Statuses=PAID&summaryOnly=True")
        
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
def sync_invoice_payments():
    """Sync payment status from Xero and create payment entries for paid invoices"""
    try:
        # Get unpaid invoices from ERPNext that have Xero invoice numbers
        unpaid_invoices = frappe.get_all("Sales Invoice", 
            filters={
                "custom_xero_invoice_number": ["is", "set"],
                "status": ["in", ["Unpaid", "Overdue"]]
            },
            fields=["name", "customer", "grand_total", "outstanding_amount", "custom_xero_invoice_number", "company"]
        )
        
        if not unpaid_invoices:
            return {
                "status": "success",
                "message": "No unpaid invoices found with Xero references"
            }
        
        # Get Xero invoice IDs
        invoice_ids = [invoice.custom_xero_invoice_number for invoice in unpaid_invoices]
        invoice_ids_str = ",".join(invoice_ids)
        
        # Fetch invoice details from Xero
        client = get_xero_client()
        response = client.make_request("GET", f"/invoices?IDs={invoice_ids_str}")
        
        xero_invoices = response.get("Invoices", [])
        processed_invoices = []
        
        for xero_invoice in xero_invoices:
            invoice_id = xero_invoice.get("InvoiceID")
            status = xero_invoice.get("Status")
            amount_paid = flt(xero_invoice.get("AmountPaid", 0))
            total_amount = flt(xero_invoice.get("Total", 0))
            
            # Find corresponding ERPNext invoice
            erpnext_invoice = None
            for inv in unpaid_invoices:
                if inv.custom_xero_invoice_number == invoice_id:
                    erpnext_invoice = inv
                    break
            
            if not erpnext_invoice:
                continue
            
            # Check if invoice is paid or partially paid in Xero
            if status in ["PAID", "AUTHORISED"] and amount_paid > 0:
                payment_result = create_payment_entry_from_xero(
                    erpnext_invoice, 
                    xero_invoice, 
                    amount_paid
                )
                processed_invoices.append({
                    "invoice": erpnext_invoice.name,
                    # "xero_id": invoice_id,
                    "amount_paid": amount_paid,
                    # "payment_result": payment_result
                })
        
        return {
            "status": "success",
            "message": f"Processed {len(processed_invoices)} invoices",
            "data": processed_invoices
        }
        
    except Exception as e:
        frappe.log_error("Xero Payment Sync", f"Error syncing invoice payments: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


def create_payment_entry_from_xero(erpnext_invoice, xero_invoice, amount_paid):
    """Create payment entry in ERPNext based on Xero payment data"""
    try:
        # Get payment details from Xero
        invoice_id = xero_invoice.get("InvoiceID")
        client = get_xero_client()
        
        # Fetch payments for this specific invoice
        payments_response = client.make_request("GET", f"/Payments?where=Invoice.InvoiceID%3DGuid%28%22{invoice_id}%22%29")
        payments = payments_response.get("Payments", [])
        
        if not payments:
            return {"status": "error", "message": "No payments found in Xero"}
        
        # Get the Sales Invoice document
        sales_invoice = frappe.get_doc("Sales Invoice", erpnext_invoice.name)
        
        # Check if payment entry already exists
        existing_payments = frappe.get_all("Payment Entry", 
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice.name,
                "docstatus": 1
            },
            fields=["name", "paid_amount"]
        )
        
        total_existing_payments = sum([flt(pe.paid_amount) for pe in existing_payments])
        remaining_amount = flt(amount_paid) - total_existing_payments
        
        if remaining_amount <= 0:
            return {"status": "info", "message": "Payment already recorded"}
        
        # Get the latest payment from Xero for reference
        latest_payment = max(payments, key=lambda x: x.get("UpdatedDateUTC", ""))
        payment_date = latest_payment.get("Date", "")
        
        # Parse Xero date format
        if payment_date:
            # Xero date format: /Date(1234567890000+0000)/
            import re
            date_match = re.search(r'/Date\((\d+)', payment_date)
            if date_match:
                timestamp = int(date_match.group(1)) / 1000
                payment_date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
            else:
                payment_date = frappe.utils.today()
        else:
            payment_date = frappe.utils.today()
        
        # Create Payment Entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = sales_invoice.customer
        payment_entry.company = sales_invoice.company
        payment_entry.posting_date = payment_date
        payment_entry.paid_amount = remaining_amount
        payment_entry.received_amount = remaining_amount
        payment_entry.reference_no = latest_payment.get("Reference", f"Xero-{invoice_id[:8]}")
        payment_entry.reference_date = payment_date
        payment_entry.remarks = f"Payment synced from Xero for Invoice {sales_invoice.name}"
        
        # Set accounts
        company_doc = frappe.get_doc("Company", sales_invoice.company)
        payment_entry.paid_to = company_doc.default_cash_account or company_doc.default_bank_account
        payment_entry.paid_from = company_doc.default_bank_account or frappe.get_value("Customer", sales_invoice.customer, "default_receivable_account")
        
        if not payment_entry.paid_from:
            payment_entry.paid_from = company_doc.default_receivable_account
        
        # Add reference to the Sales Invoice
        payment_entry.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": sales_invoice.name,
            "allocated_amount": remaining_amount
        })
        
        # Save and submit
        payment_entry.insert()
        payment_entry.submit()
        
        return {
            "status": "success", 
            "message": f"Payment Entry {payment_entry.name} created",
            "payment_entry": payment_entry.name
        }
        
    except Exception as e:
        frappe.log_error("Xero Payment Entry Creation", f"Error creating payment entry: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def check_invoice_payment_status(sales_invoice_name):
    """Check payment status of a specific invoice in Xero"""
    try:
        # Get the Sales Invoice
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        if not sales_invoice.custom_xero_invoice_number:
            return {
                "status": "error",
                "message": "No Xero invoice number found"
            }
        
        # Get invoice details from Xero
        client = get_xero_client()
        response = client.make_request("GET", f"/invoices/{sales_invoice.custom_xero_invoice_number}")
        
        if not response or "Invoices" not in response:
            return {
                "status": "error",
                "message": "Invoice not found in Xero"
            }
        
        xero_invoice = response["Invoices"][0]
        
        return {
            "status": "success",
            "data": {
                "invoice_id": xero_invoice.get("InvoiceID"),
                "status": xero_invoice.get("Status"),
                "total": xero_invoice.get("Total"),
                "amount_paid": xero_invoice.get("AmountPaid"),
                "amount_due": xero_invoice.get("AmountDue"),
                "is_paid": xero_invoice.get("Status") == "PAID",
                "is_partially_paid": flt(xero_invoice.get("AmountPaid", 0)) > 0 and xero_invoice.get("Status") != "PAID"
            }
        }
        
    except Exception as e:
        frappe.log_error("Xero Payment Status Check", f"Error checking payment status: {str(e)}")
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
            frappe.log_error("Xero Get Invoice", f"Failed to get invoice: {str(e)}")
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

# @frappe.whitelist()
# def get_xero_invoices():
#     """Get Xero invoices"""
#     try:
#         client = get_xero_client()
#         response = client.make_request("GET", "/Invoices")
        
#         return {
#             "status": "success",
#             "data": response.get("Invoices", [])
#         }
        
#     except Exception as e:
#         return {
#             "status": "error",
#             "message": str(e)
#         }

# def get_invoice(invoice_id):
#         """Get invoice from Xero"""
#         try:
#             client = get_xero_client()
#             response = client.make_request("GET", f"Invoices/{invoice_id}")
            
#             if response and "Invoices" in response:
#                 return {
#                     "status": "success",
#                     "data": response["Invoices"][0]
#                 }
            
#             return None
            
#         except Exception as e:
#             frappe.log_error(f"Failed to get invoice: {str(e)}", "Xero Get Invoice")
#             return None


# @frappe.whitelist() 
# def create_invoice(doc, method=None):
#     """Create invoice in Xero"""
#     try:
#         client = get_xero_client()
        
#         # Get the Sales Invoice document
#         if isinstance(doc, str):
#             invoice = frappe.get_doc("Sales Invoice", doc)
#         else:
#             invoice = doc
        
#         # Get customer contact ID from Xero
#         contact_id = get_customer_contact_id(invoice.customer)
#         if not contact_id:
#             frappe.throw(f"No Xero contact ID found for customer: {invoice.customer}")
        
#         # Prepare line items
#         line_items = []
#         for item in invoice.items:
#             line_item = {
#                 "Description": item.description or item.item_name,
#                 "Quantity": str(item.qty),
#                 "UnitAmount": str(item.rate),
#                 "AccountCode": item.get("custom_account_code") or "200",  # Default to 200 if not set
#             }
            
#             # Add discount rate if available
#             if item.get("discount_percentage"):
#                 line_item["DiscountRate"] = str(item.discount_percentage)
            
#             line_items.append(line_item)
        
#         # Prepare invoice data
#         invoice_data = {
#             "Type": "ACCREC",  # Accounts Receivable
#             "Contact": {
#                 "ContactID": contact_id
#             },
#             "DateString": invoice.posting_date.strftime("%Y-%m-%d") if invoice.posting_date else None,
#             "DueDateString": invoice.due_date.strftime("%Y-%m-%d") if invoice.due_date else None,
#             "LineAmountTypes": "Exclusive",  # Tax exclusive
#             "LineItems": line_items,
#             "Reference": invoice.name,  # ERPNext invoice reference
#             "Status": "AUTHORISED"  # Create as draft initially
#         }
        
#         # Add currency if different from base currency
#         if invoice.currency and invoice.currency != frappe.get_cached_value("Company", invoice.company, "default_currency"):
#             invoice_data["CurrencyCode"] = invoice.currency
        
#         data = {"Invoices": [invoice_data]}
#         response = client.make_request("POST", "/Invoices", data=data)
        
#         if response and "Invoices" in response:
#             xero_invoice = response["Invoices"][0]
            
#             # Update ERPNext Sales Invoice with Xero Invoice ID
#             # frappe.db.set_value("Sales Invoice", invoice.name, "custom_xero_invoice_number", xero_invoice.get("InvoiceID"))
#             # frappe.db.commit()
            
#             return {
#                 "status": "success",
#                 "data": xero_invoice,
#                 "message": f"Invoice created in Xero with ID: {xero_invoice.get('InvoiceID')}"
#             }
        
#         return {
#             "status": "error",
#             "message": "Failed to create invoice in Xero"
#         }
        
#     except Exception as e:
#         frappe.log_error("Xero Create Invoice", f"Failed to create invoice in Xero: {str(e)}")
#         frappe.throw(f"Failed to create invoice in Xero: {str(e)}")
#         return False


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
