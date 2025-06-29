# your_app/api/xero_webhook.py

import frappe
import hmac
import hashlib
import base64
import json
from frappe import _

# Replace with your webhook key from Xero Developer App


@frappe.whitelist(allow_guest=True)
def handle_webhook():
    try:
        settings = frappe.get_single("Xero Settings")
        WEBHOOK_KEY = settings.webhook_secret
        request = frappe.request
        payload = request.get_data()
        signature = request.headers.get("X-Xero-Signature")

        if not is_valid_signature(payload, signature, WEBHOOK_KEY):
            frappe.log_error("Invalid Xero Webhook Signature", f"Xero Webhook: \n Paylad :{payload} \n Signature :{signature}")
            frappe.response['http_status_code'] = 400
            return "Invalid signature"

        data = json.loads(payload)
        # frappe.enqueue("xero_erpnext_integration.xero_erpnext_integration.apis.webhook.process_events", queue='long', job_name='Process Xero Webhook', data=data)

        frappe.response['http_status_code'] = 200
        return "Webhook received"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Xero Webhook Error")
        frappe.response['http_status_code'] = 500
        return f"Internal error: {e}"

def is_valid_signature(payload, signature, WEBHOOK_KEY):
    

    digest = hmac.new(
        key=WEBHOOK_KEY.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).digest()

    expected_signature = base64.b64encode(digest).decode()

    frappe.log_error("Xero Webhook Signature", f"Expected Signature: {expected_signature} \n Signature: {signature}")

    if not signature:
        return False

    
    return hmac.compare_digest(expected_signature, signature)


def process_events(data):
    events = data.get("events", [])
    for event in events:
        tenant_id = event.get("tenantId")
        event_type = event.get("eventType")
        event_category = event.get("eventCategory")
        resource_id = event.get("resourceId")

        # Handle event
        frappe.log_error("Xero Wwbhook Event", f"Xero Webhook Event: {event_type} - {event_category} - {resource_id}")

        # You can also sync specific invoice/payment, e.g.:
        # from .sync import sync_invoice_from_xero
        # if event_category == "INVOICE":
        #     sync_invoice_from_xero(resource_id, tenant_id)
