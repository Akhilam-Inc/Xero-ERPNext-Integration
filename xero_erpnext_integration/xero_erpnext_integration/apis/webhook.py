# your_app/api/xero_webhook.py

import frappe
import hmac
import hashlib
import base64
import json
from frappe import _

# Replace with your webhook key from Xero Developer App
WEBHOOK_KEY = frappe.db.get_single_value("Xero Settings", "webhook_secret")

@frappe.whitelist(allow_guest=True)
def handle_webhook():
    try:
        request = frappe.request
        payload = request.get_data()
        signature = request.headers.get("X-Xero-Signature")

        if not is_valid_signature(payload, signature):
            frappe.log_error("Invalid Xero Webhook Signature", "Xero Webhook")
            frappe.response['http_status_code'] = 400
            return "Invalid signature"

        data = json.loads(payload)
        frappe.enqueue("your_app.api.xero_webhook.process_events", queue='long', job_name='Process Xero Webhook', data=data)

        frappe.response['http_status_code'] = 200
        return "Webhook received"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Xero Webhook Error")
        frappe.response['http_status_code'] = 500
        return "Internal error"

def is_valid_signature(payload, signature):
    digest = hmac.new(
        key=WEBHOOK_KEY.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(digest).decode()
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
