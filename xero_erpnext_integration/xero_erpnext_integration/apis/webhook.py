import frappe
import json
import hashlib
import hmac
import base64
from frappe import _
from frappe.utils import now_datetime, cstr

@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook():
    settings = frappe.get_single("Xero Settings")
    webhook_key = settings.webhook_secret
    request = frappe.local.request

    provided_signature = request.headers.get('X-Xero-Signature')
    hashed = hmac.new(bytes(settings.xero_webhook_key, 'utf8'), request.data, hashlib.sha256)
    generated_signature = base64.b64encode(hashed.digest()).decode('utf-8')
    if provided_signature != generated_signature:
        return '', 401
    req_data = request.json()
    if len(req_data['events']):  # assume this is intent to receive request
        # process_events(req_data['events'])
        return '', 200
    return '', 200

# def process_events(events):
#     for event in events:
#         if event['eventCategory'] == 'INVOICE':
#             invoice = client.invoices(id=event['resourceId'])
#             if invoice['Status'] == 'PAID':
#                 print('NEW PAID INVOICE:')
#                 pprint(invoice, '\n\n')
#             else:
#                 pprint(f'Received a non-paid invoice {event["eventType"]}: {invoice["InvoiceID"]}')

@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """
    Handle incoming Xero webhook requests
    """
    try:
        # Get the raw data and headers
        data = frappe.local.request.get_data()
        headers = frappe.local.request.headers
        
        # Verify webhook signature
        if not verify_webhook_signature(data, headers):
            frappe.throw(_("Invalid webhook signature"), frappe.AuthenticationError)
        
        # Parse the JSON payload
        payload = json.loads(data.decode('utf-8'))
        
        # Process each event in the payload
        for event in payload.get('events', []):
            process_webhook_event(event, payload)
        
        return {"status": "success", "message": "Webhook processed successfully"}
        
    except Exception as e:
        frappe.log_error(f"Xero Webhook Error: {str(e)}", "Xero Webhook Handler")
        frappe.throw(_("Error processing webhook: {0}").format(str(e)))

def verify_webhook_signature(payload, headers):
    """
    Verify the webhook signature from Xero
    """
    try:
        # Get webhook key from site config or system settings
        webhook_key = frappe.conf.get('xero_webhook_key') or get_xero_webhook_key()
        
        if not webhook_key:
            frappe.log_error("Xero webhook key not configured", "Xero Webhook Verification")
            return False
        
        # Get signature from headers
        signature = headers.get('X-Xero-Signature')
        if not signature:
            return False
        
        # Calculate expected signature
        expected_signature = base64.b64encode(
            hmac.new(
                webhook_key.encode('utf-8'),
                payload,
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception as e:
        frappe.log_error(f"Signature verification error: {str(e)}", "Xero Webhook Verification")
        return False

def get_xero_webhook_key():
    """
    Get Xero webhook key from system settings or custom settings
    """
    # You can store this in a custom DocType for Xero Settings
    try:
        settings = frappe.get_single('Xero Settings')
        return settings.webhook_key
    except:
        return None

def process_webhook_event(event, full_payload):
    """
    Process individual webhook event
    """
    try:
        # Create webhook log entry
        webhook_log = frappe.get_doc({
            'doctype': 'Xero Webhook Log',
            'webhook_id': event.get('eventId'),
            'event_category': event.get('eventCategory'),
            'event_type': event.get('eventType'),
            'resource_id': event.get('resourceId'),
            'resource_url': event.get('resourceUrl'),
            'tenant_id': event.get('tenantId'),
            'tenant_type': event.get('tenantType'),
            'timestamp': now_datetime(),
            'status': 'Pending',
            'payload': json.dumps(full_payload, indent=2)
        })
        webhook_log.insert(ignore_permissions=True)
        
        # Process based on event type
        event_category = event.get('eventCategory')
        event_type = event.get('eventType')
        
        if event_category == 'INVOICE':
            handle_invoice_event(event, webhook_log)
        elif event_category == 'CONTACT':
            handle_contact_event(event, webhook_log)
        elif event_category == 'PAYMENT':
            handle_payment_event(event, webhook_log)
        else:
            # Log unhandled event types
            webhook_log.status = 'Processed'
            webhook_log.error_message = f'Unhandled event category: {event_category}'
            webhook_log.save(ignore_permissions=True)
        
        frappe.db.commit()
        
    except Exception as e:
        # Update webhook log with error
        if 'webhook_log' in locals():
            webhook_log.status = 'Failed'
            webhook_log.error_message = str(e)
            webhook_log.save(ignore_permissions=True)
        
        frappe.log_error(f"Error processing webhook event: {str(e)}", "Xero Webhook Event Processing")
        raise

def handle_invoice_event(event, webhook_log):
    """
    Handle invoice-related webhook events
    """
    try:
        event_type = event.get('eventType')
        resource_id = event.get('resourceId')
        
        if event_type == 'CREATE':
            # Handle new invoice creation
            sync_invoice_from_xero(resource_id)
        elif event_type == 'UPDATE':
            # Handle invoice updates
            update_invoice_from_xero(resource_id)
        elif event_type == 'DELETE':
            # Handle invoice deletion
            handle_invoice_deletion(resource_id)
        
        webhook_log.status = 'Processed'
        webhook_log.save(ignore_permissions=True)
        
    except Exception as e:
        webhook_log.status = 'Failed'
        webhook_log.error_message = str(e)
        webhook_log.save(ignore_permissions=True)
        raise

def handle_contact_event(event, webhook_log):
    """
    Handle contact-related webhook events
    """
    try:
        event_type = event.get('eventType')
        resource_id = event.get('resourceId')
        
        if event_type == 'CREATE':
            sync_customer_from_xero(resource_id)
        elif event_type == 'UPDATE':
            update_customer_from_xero(resource_id)
        
        webhook_log.status = 'Processed'
        webhook_log.save(ignore_permissions=True)
        
    except Exception as e:
        webhook_log.status = 'Failed'
        webhook_log.error_message = str(e)
        webhook_log.save(ignore_permissions=True)
        raise

def handle_payment_event(event, webhook_log):
    """
    Handle payment-related webhook events
    """
    try:
        event_type = event.get('eventType')
        resource_id = event.get('resourceId')
        
        if event_type == 'CREATE':
            sync_payment_from_xero(resource_id)
        elif event_type == 'UPDATE':
            update_payment_from_xero(resource_id)
        
        webhook_log.status = 'Processed'
        webhook_log.save(ignore_permissions=True)
        
    except Exception as e:
        webhook_log.status = 'Failed'
        webhook_log.error_message = str(e)
        webhook_log.save(ignore_permissions=True)
        raise

# Placeholder functions for actual Xero API integration
def sync_invoice_from_xero(invoice_id):
    """
    Sync invoice from Xero to Frappe
    Implement your Xero API call here
    """
    frappe.log_error(f"Syncing invoice {invoice_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration

def update_invoice_from_xero(invoice_id):
    """
    Update existing invoice from Xero
    """
    frappe.log_error(f"Updating invoice {invoice_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration

def handle_invoice_deletion(invoice_id):
    """
    Handle invoice deletion from Xero
    """
    frappe.log_error(f"Handling deletion of invoice {invoice_id}", "Xero Sync")
    # TODO: Implement logic to handle deleted invoices

def sync_customer_from_xero(contact_id):
    """
    Sync customer from Xero to Frappe
    """
    frappe.log_error(f"Syncing customer {contact_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration

def update_customer_from_xero(contact_id):
    """
    Update existing customer from Xero
    """
    frappe.log_error(f"Updating customer {contact_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration

def sync_payment_from_xero(payment_id):
    """
    Sync payment from Xero to Frappe
    """
    frappe.log_error(f"Syncing payment {payment_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration

def update_payment_from_xero(payment_id):
    """
    Update existing payment from Xero
    """
    frappe.log_error(f"Updating payment {payment_id} from Xero", "Xero Sync")
    # TODO: Implement actual Xero API integration
