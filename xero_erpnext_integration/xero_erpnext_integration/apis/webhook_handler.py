import frappe
from frappe import _
from frappe.utils import now, flt, getdate, nowdate
import json
import hmac
import hashlib
import base64
from .base import get_xero_client

class XeroWebhookHandler:
    """
    Handle incoming webhooks from Xero
    Process payment updates and sync back to ERPNext
    """
    
    def __init__(self):
        self.xero_client = get_xero_client()
        self.settings = frappe.get_single("Xero Settings")
    
    def verify_signature(self, payload, signature):
        """
        Verify webhook signature using HMAC-SHA256
        Returns tuple: (is_valid, should_verify)
        """
        try:
            webhook_secret = self.settings.webhook_secret
            
            # If no secret configured, skip verification
            if not webhook_secret:
                return True, False
            
            # If secret is configured but no signature provided, fail
            if not signature:
                frappe.log_error("Xero Webhook", "Webhook secret configured but no signature provided")
                return False, True
            
            # Ensure payload is bytes for HMAC calculation
            payload_bytes = payload.encode('utf-8') if isinstance(payload, str) else payload
            
            # Calculate expected signature
            expected_signature = base64.b64encode(
                hmac.new(
                    webhook_secret.encode('utf-8'),
                    payload_bytes,
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            # Compare signatures
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if not is_valid:
                frappe.log_error("Xero Webhook", f"Signature mismatch. Expected: {expected_signature}, Got: {signature}")
            
            return is_valid, True
            
        except Exception as e:
            frappe.log_error("Xero Webhook Signature", f"Signature verification failed: {str(e)}")
            return False, True
    
    def process_webhook(self, payload, signature=None):
        """
        Process incoming webhook from Xero
        """
        try:
            # Debug: Log raw payload info
            frappe.log_error("webhook log", f"Raw payload type: {type(payload)}")
            frappe.log_error("webhook log", f"Raw payload length: {len(payload) if payload else 0}")
            
            # Handle empty payload
            if not payload:
                return {"status": "error", "message": "Empty payload received"}
            
            # Convert payload to string if it's bytes
            if isinstance(payload, bytes):
                payload_str = payload.decode('utf-8')
            elif isinstance(payload, str):
                payload_str = payload
            else:
                payload_str = json.dumps(payload)
            
            # Debug: Log processed payload
            frappe.log_error("webhook log", f"Processed payload: {payload_str[:200]}...")  # First 200 chars
            
            # Handle empty string
            if not payload_str.strip():
                return {"status": "error", "message": "Empty payload string received"}
            
            # Parse webhook payload first (before signature verification)
            try:
                webhook_data = json.loads(payload_str)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON payload: {str(e)}. Payload: {payload_str[:500]}"
                frappe.log_error("Xero Webhook JSON Parse Error", error_msg)
                return {"status": "error", "message": f"Invalid JSON payload: {str(e)}"}
            
            # Validate webhook data structure
            if not isinstance(webhook_data, dict):
                return {"status": "error", "message": "Webhook payload must be a JSON object"}
            
            # Log webhook received
            self._log_webhook("Received", webhook_data)
            
            # Process each event in the webhook
            results = []
            events = webhook_data.get("events", [])
            
            if not events:
                return {"status": "success", "message": "No events to process", "processed_events": 0}
            
            for event in events:
                try:
                    result = self._process_event(event)
                    results.append(result)
                except Exception as e:
                    error_msg = f"Failed to process event {event.get('eventId', 'unknown')}: {str(e)}"
                    frappe.log_error("Xero Webhook Event Error", error_msg)
                    results.append({"status": "error", "message": error_msg})
            
            return {"status": "success", "processed_events": len(results), "results": results}
            
        except Exception as e:
            error_msg = f"Webhook processing failed: {str(e)}"
            frappe.log_error("Xero Webhook Error", error_msg)
            self._log_webhook("Error", {
                "error": error_msg, 
                "payload_type": str(type(payload)),
                "payload_length": len(payload) if payload else 0,
                "payload_preview": str(payload)[:200] if payload else "None"
            })
            return {"status": "error", "message": error_msg}

    # ... rest of your existing methods remain the same ...
    def _process_event(self, event):
        """Process individual webhook event"""
        if not isinstance(event, dict):
            return {"status": "error", "message": "Invalid event format"}
        
        event_category = event.get("eventCategory")
        event_type = event.get("eventType")
        resource_url = event.get("resourceUrl")
        resource_id = event.get("resourceId")
        
        # Log event processing
        frappe.log_error("webhook log", f"Processing Xero webhook event: {event_category}.{event_type} for resource {resource_id}")
        
        # Handle different event types
        if event_category == "INVOICE" and event_type == "UPDATE":
            return self._handle_invoice_update(resource_url, resource_id)
        elif event_category == "PAYMENT" and event_type == "CREATE":
            return self._handle_payment_create(resource_url, resource_id)
        elif event_category == "PAYMENT" and event_type == "UPDATE":
            return self._handle_payment_update(resource_url, resource_id)
        else:
            return {"status": "ignored", "message": f"Event type {event_category}.{event_type} not handled"}

    # ... include all your other existing methods here ...
    def _handle_invoice_update(self, resource_url, resource_id):
        """Handle invoice update events"""
        try:
            # Get invoice details from Xero
            xero_invoice = self.xero_client.get_invoice(resource_id)
            
            if not xero_invoice:
                return {"status": "error", "message": "Invoice not found in Xero"}
            
            # Find corresponding ERPNext Sales Invoice
            sales_invoice = self._find_erpnext_invoice(xero_invoice.invoice_number, resource_id)
            
            if not sales_invoice:
                return {"status": "ignored", "message": "Corresponding ERPNext invoice not found"}
            
            # Check if invoice status changed to paid
            if xero_invoice.status == "PAID" and sales_invoice.status != "Paid":
                return self._create_payment_entry(sales_invoice, xero_invoice)
            
            return {"status": "success", "message": "Invoice status updated"}
            
        except Exception as e:
            error_msg = f"Failed to handle invoice update: {str(e)}"
            frappe.log_error("Xero Invoice Update Handler", error_msg)
            return {"status": "error", "message": error_msg}

    def _handle_payment_create(self, resource_url, resource_id):
        """Handle payment creation events"""
        try:
            # Get payment details from Xero
            payments = self.xero_client.get_payments()
            xero_payment = None
            
            for payment in payments:
                if payment.payment_id == resource_id:
                    xero_payment = payment
                    break
            
            if not xero_payment:
                return {"status": "error", "message": "Payment not found in Xero"}
            
            # Process payment for each invoice
            results = []
            if hasattr(xero_payment, 'invoice') and xero_payment.invoice:
                invoice_id = xero_payment.invoice.invoice_id
                
                # Get invoice details
                xero_invoice = self.xero_client.get_invoice(invoice_id)
                if xero_invoice:
                    sales_invoice = self._find_erpnext_invoice(xero_invoice.invoice_number, invoice_id)
                    if sales_invoice:
                        result = self._create_payment_entry_from_payment(sales_invoice, xero_payment)
                        results.append(result)
            
            return {"status": "success", "results": results}
            
        except Exception as e:
            error_msg = f"Failed to handle payment creation: {str(e)}"
            frappe.log_error("Xero Payment Create Handler", error_msg)
            return {"status": "error", "message": error_msg}

    def _handle_payment_update(self, resource_url, resource_id):
        """Handle payment update events"""
        # Similar to payment create but for updates
        return self._handle_payment_create(resource_url, resource_id)

    def _find_erpnext_invoice(self, invoice_number, xero_invoice_id):
        """Find ERPNext Sales Invoice by invoice number or Xero ID"""
        try:
            # First try to find by Xero invoice ID
            invoices = frappe.get_all("Sales Invoice",
                                    filters={"custom_xero_invoice_id": xero_invoice_id},
                                   fields=["name"])
            
            if invoices:
                return frappe.get_doc("Sales Invoice", invoices[0].name)
            
            # Then try to find by invoice number
            invoices = frappe.get_all("Sales Invoice",
                                    filters={"name": invoice_number},
                                   fields=["name"])
            
            if invoices:
                return frappe.get_doc("Sales Invoice", invoices[0].name)
            
            return None
            
        except Exception as e:
            frappe.log_error("Xero Invoice Lookup", f"Error finding ERPNext invoice: {str(e)}")
            return None

    def _create_payment_entry(self, sales_invoice, xero_invoice):
        """Create Payment Entry in ERPNext based on Xero invoice payment"""
        try:
            # Check if payment entry already exists
            existing_payments = frappe.get_all("Payment Entry",
                                             filters={
                                                "reference_doctype": "Sales Invoice",
                                                "reference_name": sales_invoice.name,
                                                "custom_xero_payment_id": ["!=", ""]
                                            })
            
            if existing_payments:
                return {"status": "ignored", "message": "Payment entry already exists"}
            
            # Get payment details from Xero
            payments = self.xero_client.get_payments(invoice_id=xero_invoice.invoice_id)
            
            if not payments:
                return {"status": "error", "message": "No payments found for invoice"}
            
            # Create payment entry for each payment
            results = []
            for payment in payments:
                result = self._create_payment_entry_from_payment(sales_invoice, payment)
                results.append(result)
            
            return {"status": "success", "results": results}
            
        except Exception as e:
            error_msg = f"Failed to create payment entry: {str(e)}"
            frappe.log_error("Xero Payment Entry Creation", error_msg)
            return {"status": "error", "message": error_msg}

    def _create_payment_entry_from_payment(self, sales_invoice, xero_payment):
        """Create Payment Entry from Xero payment object"""
        try:
            # Prepare payment entry data
            payment_entry = frappe.new_doc("Payment Entry")
            payment_entry.payment_type = "Receive"
            payment_entry.party_type = "Customer"
            payment_entry.party = sales_invoice.customer
            payment_entry.paid_amount = flt(xero_payment.amount)
            payment_entry.received_amount = flt(xero_payment.amount)
            payment_entry.target_exchange_rate = 1
            payment_entry.posting_date = getdate(xero_payment.date) if hasattr(xero_payment, 'date') else nowdate()
            payment_entry.reference_no = xero_payment.reference if hasattr(xero_payment, 'reference') else ""
            payment_entry.reference_date = payment_entry.posting_date
            
            # Set accounts
            payment_entry.paid_to = self._get_default_receivable_account(sales_invoice.company)
            payment_entry.paid_from = self._get_default_cash_account(sales_invoice.company)
            
            # Add reference to sales invoice
            payment_entry.append("references", {
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice.name,
                "allocated_amount": flt(xero_payment.amount)
            })
            
            # Add Xero payment details
            payment_entry.custom_xero_payment_id = xero_payment.payment_id
            payment_entry.custom_xero_sync_status = "Synced"
            payment_entry.custom_xero_sync_date = nowdate()
            
            # Save and submit payment entry
            payment_entry.insert(ignore_permissions=True)
            payment_entry.submit()
            
            return {
                "status": "success", 
                "payment_entry": payment_entry.name,
                "amount": flt(xero_payment.amount)
            }
            
        except Exception as e:
            error_msg = f"Failed to create payment entry from Xero payment: {str(e)}"
            frappe.log_error("Xero Payment Entry Creation", error_msg)
            return {"status": "error", "message": error_msg}

    def _get_default_receivable_account(self, company):
        """Get default receivable account for company"""
        try:
            company_doc = frappe.get_doc("Company", company)
            return company_doc.default_receivable_account
        except:
            # Fallback to first receivable account
            accounts = frappe.get_all("Account",
                                    filters={
                                       "company": company,
                                       "account_type": "Receivable",
                                       "is_group": 0
                                   },
                                   limit=1)
            return accounts[0].name if accounts else None

    def _get_default_cash_account(self, company):
        """Get default cash account for company"""
        try:
            company_doc = frappe.get_doc("Company", company)
            return company_doc.default_cash_account
        except:
            # Fallback to first cash account
            accounts = frappe.get_all("Account",
                                    filters={
                                       "company": company,
                                       "account_type": "Cash",
                                       "is_group": 0
                                   },
                                   limit=1)
            return accounts[0].name if accounts else None

    def _log_webhook(self, status, data):
        """Log webhook activity"""
        try:
            if not self.settings.debug_mode:
                return
                
            log_doc = frappe.get_doc({
                "doctype": "Xero API Log",
                "api_method": "WEBHOOK",
                "api_url": "/webhook",
                "status_code": 200 if status == "Received" else 500,
                "message": f"Webhook {status}",
                "payload": json.dumps(data, indent=2),
                "timestamp": now(),
                # "tenant_id": self.settings.tenant_id
            })
            
            log_doc.insert(ignore_permissions=True)
            
        except Exception as e:
            frappe.log_error("Xero Webhook Log Error", f"Failed to log webhook: {str(e)}")


# API endpoint for webhook
@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_xero_webhook():
    """
    Public endpoint to handle Xero webhooks
    URL: /api/method/xero_erpnext_integration.apis.webhook_handler.handle_xero_webhook
    """
    try:
        # Get request data - try multiple methods
        payload = None
        
        # Method 1: Get raw data
        try:
            payload = frappe.request.get_data()
            frappe.log_error("webhook log", f"Method 1 - Raw data: {type(payload)}, length: {len(payload) if payload else 0}")
        except Exception as e:
            frappe.log_error("webhook log", f"Method 1 failed: {str(e)}")
        
        # Method 2: Try form data if raw data is empty
        if not payload:
            try:
                payload = frappe.request.form.to_dict()
                frappe.log_error("webhook log", f"Method 2 - Form data: {payload}")
            except Exception as e:
                frappe.log_error("webhook log", f"Method 2 failed: {str(e)}")
        
        # Method 3: Try JSON data
        if not payload:
            try:
                payload = frappe.request.get_json()
                frappe.log_error("webhook log", f"Method 3 - JSON data: {payload}")
            except Exception as e:
                frappe.log_error("webhook log", f"Method 3 failed: {str(e)}")
        
        # Method 4: Try request data as string
        if not payload:
            try:
                payload = frappe.request.data
                frappe.log_error("webhook log", f"Method 4 - Request data: {type(payload)}, length: {len(payload) if payload else 0}")
            except Exception as e:
                frappe.log_error("webhook log", f"Method 4 failed: {str(e)}")
        
        # Log all request headers for debugging
        frappe.log_error("webhook log", f"Request headers: {dict(frappe.request.headers)}")
        frappe.log_error("webhook log", f"Request method: {frappe.request.method}")
        frappe.log_error("webhook log", f"Request content type: {frappe.request.content_type}")
        
        # If still no payload, return error with debug info
        if not payload:
            error_msg = "No payload received from webhook"
            frappe.log_error("Xero Webhook No Payload", f"{error_msg}. Headers: {dict(frappe.request.headers)}")
            frappe.local.response["http_status_code"] = 400
            return {
                "status": "error", 
                "message": error_msg,
                "debug_info": {
                    "headers": dict(frappe.request.headers),
                    "method": frappe.request.method,
                    "content_type": frappe.request.content_type
                }
            }
        
        # Get signature from headers
        signature = frappe.request.headers.get("X-Xero-Signature")
        
        # Initialize handler
        handler = XeroWebhookHandler()
        
        # **CRITICAL FIX**: Verify signature BEFORE processing
        # Convert payload to string for signature verification
        if isinstance(payload, bytes):
            payload_str = payload.decode('utf-8')
        elif isinstance(payload, str):
            payload_str = payload
        else:
            payload_str = json.dumps(payload)
        
        # Verify signature first
        is_valid, should_verify = handler.verify_signature(payload_str, signature)
        
        if should_verify and not is_valid:
            # Return 401 for invalid signature - this is what Xero expects
            frappe.local.response["http_status_code"] = 401
            error_response = {
                "status": "error", 
                "message": "Invalid webhook signature"
            }
            frappe.response["message"] = error_response
            return error_response
        
        # Process webhook only if signature is valid
        result = handler.process_webhook(payload)
        
        # Set appropriate HTTP status code
        if result.get("status") == "success":
            frappe.local.response["http_status_code"] = 200
        else:
            frappe.local.response["http_status_code"] = 400
        
        frappe.response["message"] = result
        return result
        
    except Exception as e:
        error_msg = f"Webhook endpoint error: {str(e)}"
        frappe.log_error("Xero Webhook Endpoint", error_msg)
        
        frappe.local.response["http_status_code"] = 500
        error_response = {"status": "error", "message": error_msg}
        frappe.response["message"] = error_response
        
        return error_response


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def handle_xero_webhook_intent():
    """
    Handle Xero webhook intent to receive verification
    This endpoint must return 200 OK for Xero to activate the webhook
    URL: /api/method/xero_erpnext_integration.apis.webhook_handler.handle_xero_webhook_intent
    """
    try:
        key = frappe.get_single("Xero Settings").webhook_secret
        provided_signature = frappe.request.headers.get('X-Xero-Signature')
        hashed = hmac.new(bytes(key, 'utf8'), frappe.request.get_data(), hashlib.sha256)
        generated_signature = base64.b64encode(hashed.digest()).decode('utf-8')
        frappe.log_error("Xero Webhook Signature", f"Provided Signature: {provided_signature}, Generated Signature: {generated_signature}")
        if provided_signature != generated_signature:
            return '', 401
        else:
            return '', 200
        # # Capture all request details for analysis
        # request_details = {
        #     "method": frappe.request.method,
        #     "url": frappe.request.url,
        #     "base_url": frappe.request.base_url,
        #     "path": frappe.request.path,
        #     "query_string": frappe.request.query_string.decode('utf-8') if frappe.request.query_string else "",
        #     "content_type": frappe.request.content_type,
        #     "content_length": frappe.request.content_length,
        #     "remote_addr": frappe.request.remote_addr,
        #     "user_agent": frappe.request.headers.get('User-Agent', ''),
        #     "timestamp": now(),
        #     "request": frappe.request.headers.get('X-Xero-Signature', '')
        # }
        
        # # Capture all headers
        # headers = {}
        # for key, value in frappe.request.headers:
        #     headers[key] = value
        # request_details["headers"] = headers
        
        # # Capture query parameters
        # args = {}
        # for key, value in frappe.request.args.items():
        #     args[key] = value
        # request_details["query_params"] = args
        
        # # Capture form data if present
        # form_data = {}
        # try:
        #     if frappe.request.form:
        #         for key, value in frappe.request.form.items():
        #             form_data[key] = value
        #     request_details["form_data"] = form_data
        # except Exception as form_error:
        #     request_details["form_data_error"] = str(form_error)
        
        # # Capture payload using multiple methods
        # payload_info = {}
        
        # # Method 1: Get raw data
        # try:
        #     raw_data = frappe.request.get_data()
        #     payload_info["raw_data"] = {
        #         "type": str(type(raw_data)),
        #         "length": len(raw_data) if raw_data else 0,
        #         "content": raw_data.decode('utf-8') if isinstance(raw_data, bytes) else str(raw_data) if raw_data else ""
        #     }
        # except Exception as e:
        #     payload_info["raw_data_error"] = str(e)
        
        # # Method 2: Try JSON data
        # try:
        #     json_data = frappe.request.get_json()
        #     payload_info["json_data"] = {
        #         "type": str(type(json_data)),
        #         "content": json_data
        #     }
        # except Exception as e:
        #     payload_info["json_data_error"] = str(e)
        
        # # Method 3: Try request.data
        # try:
        #     request_data = frappe.request.data
        #     payload_info["request_data"] = {
        #         "type": str(type(request_data)),
        #         "length": len(request_data) if request_data else 0,
        #         "content": request_data.decode('utf-8') if isinstance(request_data, bytes) else str(request_data) if request_data else ""
        #     }
        # except Exception as e:
        #     payload_info["request_data_error"] = str(e)
        
        # request_details["payload_info"] = payload_info
        
        # # Parse the main payload for Xero-specific data
        # xero_payload = None
        # payload_str = ""
        
        # # Get the best available payload
        # if payload_info.get("raw_data", {}).get("content"):
        #     payload_str = payload_info["raw_data"]["content"]
        # elif payload_info.get("request_data", {}).get("content"):
        #     payload_str = payload_info["request_data"]["content"]
        # elif payload_info.get("json_data", {}).get("content"):
        #     xero_payload = payload_info["json_data"]["content"]
        #     payload_str = json.dumps(xero_payload) if xero_payload else ""
        
        # # Parse JSON payload if we have a string
        # if payload_str and not xero_payload:
        #     try:
        #         xero_payload = json.loads(payload_str)
        #     except json.JSONDecodeError as e:
        #         request_details["json_parse_error"] = str(e)
        
        # # Analyze Xero-specific payload structure
        # xero_analysis = {}
        # if xero_payload and isinstance(xero_payload, dict):
        #     xero_analysis = {
        #         "events": xero_payload.get("events", []),
        #         "entropy": xero_payload.get("entropy", ""),
        #         "firstEventSequence": xero_payload.get("firstEventSequence"),
        #         "lastEventSequence": xero_payload.get("lastEventSequence"),
        #         "is_intent_verification": False
        #     }
            
        #     # Check if this is an intent verification
        #     events = xero_payload.get("events", [])
        #     entropy = xero_payload.get("entropy", "")
        #     first_seq = xero_payload.get("firstEventSequence")
        #     last_seq = xero_payload.get("lastEventSequence")
            
        #     if (isinstance(events, list) and len(events) == 0 and 
        #         entropy and first_seq == 0 and last_seq == 0):
        #         xero_analysis["is_intent_verification"] = True
        
        # request_details["xero_analysis"] = xero_analysis
        
        # # Log comprehensive request details
        # frappe.log_error("Xero Webhook Intent - Full Analysis", json.dumps(request_details, indent=2, default=str))
        
        # # Check for specific Xero webhook signatures
        # xero_signature = headers.get("X-Xero-Signature", "")
        # if xero_signature:
        #     request_details["xero_signature_present"] = True
        #     frappe.log_error("Xero Webhook Intent - Signature", f"X-Xero-Signature header found: {xero_signature[:20]}...")
        
        # # Handle different scenarios
        # if xero_analysis.get("is_intent_verification"):
        #     frappe.log_error("Xero Webhook Intent - Verification", f"Intent verification detected with entropy: {xero_analysis.get('entropy')}")
            
        #     # Xero expects HTTP 200 for intent verification
        #     frappe.local.response["http_status_code"] = 200
        #     return {
        #         "status": "success",
        #         "message": "Intent to receive acknowledged",
        #         "entropy": xero_analysis.get("entropy"),
        #         "timestamp": now()
        #     }
        
        # elif frappe.request.method == "GET":
        #     # Handle GET requests (testing/health check)
        #     frappe.local.response["http_status_code"] = 200
        #     return {
        #         "status": "success",
        #         "message": "Webhook endpoint is accessible via GET",
        #         "request_details": request_details
        #     }
        
        # else:
        #     # Handle other POST requests
        #     frappe.local.response["http_status_code"] = 200
        #     return {
        #         "status": "success",
        #         "message": "Webhook endpoint received request",
        #         "request_details": request_details
        #     }
        
    except Exception as e:
        error_msg = f"Intent to receive error: {str(e)}"
        error_details = {
            "error": error_msg,
            "error_type": str(type(e)),
            "timestamp": now()
        }
        
        # Try to capture request details even on error
        try:
            error_details.update({
                "method": frappe.request.method,
                "headers": dict(frappe.request.headers),
                "content_type": frappe.request.content_type,
            })
        except:
            pass
        
        frappe.log_error("Xero Webhook Intent Error - Full Details", json.dumps(error_details, indent=2, default=str))
        
        # Return 200 OK even on error for Xero webhook setup to succeed
        frappe.local.response["http_status_code"] = 200
        return {
            "status": "error",
            "message": "Webhook endpoint accessible but encountered error",
            "error_details": error_details
        }



# Manual webhook processing for testing
@frappe.whitelist()
def test_webhook_processing(payload):
    """Test webhook processing with sample payload"""
    try:
        handler = XeroWebhookHandler()
        return handler.process_webhook(payload)
        
    except Exception as e:
        frappe.log_error("Xero Test Webhook", f"Test webhook processing failed: {str(e)}")
        return {"status": "error", "message": str(e)}


# Test endpoint to check webhook URL accessibility
@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def test_webhook_endpoint():
    """Test endpoint to verify webhook URL is accessible"""
    try:
        method = frappe.request.method
        headers = dict(frappe.request.headers)
        
        if method == "GET":
            return {
                "status": "success",
                "message": "Webhook endpoint is accessible",
                "method": method,
                "timestamp": now()
            }
        else:
            # For POST, return request details
            payload = frappe.request.get_data()
            return {
                "status": "success",
                "message": "Webhook endpoint received POST request",
                "method": method,
                "payload_type": str(type(payload)),
                "payload_length": len(payload) if payload else 0,
                "headers": headers,
                "timestamp": now()
            }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "timestamp": now()
        }
