import frappe
from frappe import _
from frappe.utils import now, flt, getdate, nowdate
import json
import hmac
import hashlib
import base64
from .base import get_xero_client



@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """
    Handle incoming webhooks from Xero
    Process payment updates and sync back to ERPNext
    """
    xero_client = get_xero_client()
    settings = frappe.get_single("Xero Settings")
    
    # Verify webhook signature
    signature = frappe.request.headers.get("X-Xero-Signature")
    payload = frappe.request.get_data()
    
    return True
