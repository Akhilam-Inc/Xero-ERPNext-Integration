import frappe
import json
import hashlib
import hmac
import base64
from frappe import _

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def webhook():
    """Main Xero webhook endpoint"""
    try:
        request = frappe.local.request
        
        # Handle GET request for "intent to receive" challenge
        if request.method == "GET":
            return handle_intent_to_receive()
        
        # Handle POST request for actual webhook events
        elif request.method == "POST":
            return handle_webhook_event()
        
        frappe.local.response.http_status_code = 405
        return "Method Not Allowed"
        
    except Exception as e:
        frappe.log_error(f"Xero Webhook Error: {str(e)}", "Xero Webhook Handler")
        frappe.local.response.http_status_code = 500
        return "Internal Server Error"

def handle_intent_to_receive():
    """Handle Xero's intent to receive challenge (GET request)"""
    try:
        request = frappe.local.request
        
        # Get the challenge parameter from query string
        challenge = request.args.get('challenge')
        if not challenge:
            frappe.local.response.http_status_code = 400
            return "Bad Request"
        
        # Return the challenge value directly - Xero expects plain text response
        return challenge
        
    except Exception as e:
        frappe.log_error(f"Error handling intent to receive: {str(e)}", "Xero Webhook")
        frappe.local.response.http_status_code = 500
        return "Internal Server Error"

def handle_webhook_event():
    """Handle actual webhook events (POST request)"""
    try:
        settings = frappe.get_single("Xero Settings")
        webhook_key = settings.webhook_secret
        request = frappe.local.request

        # Verify webhook signature
        provided_signature = request.headers.get('X-Xero-Signature')
        if not provided_signature:
            frappe.local.response.http_status_code = 401
            return "Unauthorized"

        hashed = hmac.new(bytes(webhook_key, 'utf8'), request.data, hashlib.sha256)
        generated_signature = base64.b64encode(hashed.digest()).decode('utf-8')
        
        if not hmac.compare_digest(provided_signature, generated_signature):
            frappe.local.response.http_status_code = 401
            return "Unauthorized"

        # Process webhook payload
        try:
            # Try calling json() method first
            req_data = request.json() if callable(request.json) else request.json
        except:
            # Fallback to getting json data from request
            req_data = frappe.local.form_dict
        
        if req_data.get('events'):
            for event in req_data['events']:
                process_webhook_event(event)
        
        frappe.local.response.http_status_code = 200
        return "OK"
        
    except Exception as e:
        frappe.log_error(f"Error handling webhook event: {str(e)}", "Xero Webhook Handler")
        frappe.local.response.http_status_code = 500
        return "Internal Server Error"

def process_webhook_event(event):
    """Process individual webhook event"""
    try:
        event_category = event.get('eventCategory')
        event_type = event.get('eventType')
        resource_id = event.get('resourceId')
        
        # Only handle invoice events
        if event_category == 'INVOICE' and event_type == 'UPDATE':
            update_invoice_from_xero(resource_id)
            
    except Exception as e:
        frappe.log_error(f"Error processing webhook event: {str(e)}", "Xero Webhook Event Processing")

def update_invoice_from_xero(invoice_id):
    """Update existing invoice from Xero - handle status changes like PAID/VOIDED"""
    try:
        from .base import get_xero_client
        
        # Get invoice details from Xero
        client = get_xero_client()
        response = client.make_request("GET", f"/Invoices/{invoice_id}")
        
        if not response or "Invoices" not in response:
            frappe.log_error(f"Invoice {invoice_id} not found in Xero", "Xero Webhook")
            return
        
        xero_invoice = response["Invoices"][0]
        status = xero_invoice.get("Status")
        amount_paid = float(xero_invoice.get("AmountPaid", 0))
        
        # Find corresponding ERPNext Sales Invoice
        sales_invoice = frappe.get_all("Sales Invoice",
            filters={"custom_xero_invoice_number": invoice_id},
            fields=["name", "customer", "grand_total", "docstatus"],
            limit=1
        )
        
        if not sales_invoice:
            frappe.log_error(f"No ERPNext invoice found for Xero invoice {invoice_id}", "Xero Webhook")
            return
        
        sales_invoice = sales_invoice[0]
        
        # Handle PAID status - create payment entry
        if status == "PAID" and amount_paid > 0:
            handle_paid_invoice(sales_invoice, xero_invoice, amount_paid)
            
        # Handle VOIDED status - cancel invoice in ERPNext
        elif status == "VOIDED":
            handle_voided_invoice(sales_invoice, invoice_id)
            
        frappe.log_error(f"Successfully processed {status} invoice {invoice_id}", "Xero Webhook")
        
    except Exception as e:
        frappe.log_error(f"Error updating invoice {invoice_id} from Xero: {str(e)}", "Xero Webhook")

def handle_paid_invoice(sales_invoice, xero_invoice, amount_paid):
	"""Handle when an invoice is marked as PAID in Xero"""
	try:
		from .sales_invoice import sync_invoice_payments
		
		# Sync invoice payments from Xero
		sync_invoice_payments()
		
	except Exception as e:
		frappe.log_error(f"Error handling paid invoice {sales_invoice['name']}: {str(e)}", "Xero Webhook")

def handle_voided_invoice(sales_invoice, xero_invoice_id):
	"""Handle when an invoice is VOIDED in Xero"""
	try:
		from ..schedulers.voided_invoice_sync import sync_voided_invoices
		
		# Sync voided invoices from Xero
		sync_voided_invoices()
		
	except Exception as e:
		frappe.log_error(f"Error handling voided invoice {sales_invoice['name']}: {str(e)}", "Xero Webhook")
