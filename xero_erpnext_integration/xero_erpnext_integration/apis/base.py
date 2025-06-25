import requests
import frappe
import base64
from urllib.parse import urljoin
from enum import Enum
from frappe import _
from frappe.utils.background_jobs import enqueue

class SupportedHTTPMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"

class XeroBase:
    BASE_PATH = ""
    
    def __init__(self):
        self.config = frappe.get_single("Xero Settings")
        self.client_secret = self.config.get_password("csec")
        self.base_url = self.config.base_url
        self.enabled = self.config.enable,
        self.enable_api_log = self.config.debug_mode
        self.client_id = self.config.ccid
        
        # Create Basic Auth header
        self.headers = {
            "Authorization": self._create_basic_auth_header(),
            "Content-Type": "application/json"
        }
        self.log_data = {}
        
        if self.enabled:
            self.validate_credentials()
        else:
            frappe.throw(_("Please enable <strong>Xero</strong> integration."), title=_("Integration Disabled"))

    def _create_basic_auth_header(self):
        """Create Basic Authentication header using client_id as username and client_secret as password"""
        if not self.client_id or not self.client_secret:
            return ""
        
        # Create the credentials string: username:password
        credentials = f"{self.client_id}:{self.client_secret}"
        
        # Encode to base64
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        
        # Return the Basic Auth header
        return f"Basic {encoded_credentials}"

    def validate_credentials(self):
        if not self.client_secret:
            frappe.throw(_("Please set <strong>Xero</strong> API key."), title=_("API Key Is Missing"))
        
        if not self.client_id:
            frappe.throw(_("Please set <strong>Xero</strong> Client ID."), title=_("Client ID Is Missing"))

    def get(self, endpoint=None, params=None, headers=None):
        return self._make_request(SupportedHTTPMethod.GET, endpoint=endpoint, params=params, headers=headers)
    
    def delete(self, endpoint=None, params=None, headers=None):
        return self._make_request(SupportedHTTPMethod.DELETE, endpoint=endpoint, params=params, headers=headers)
    
    def post(self, endpoint, params=None, json=None, headers=None):
        return self._make_request(SupportedHTTPMethod.POST, endpoint,params=params, json=json, headers=headers)

    def put(self, endpoint, json=None, headers=None):
        return self._make_request(SupportedHTTPMethod.PUT, endpoint, json=json, headers=headers)

    def _make_request(self, method: SupportedHTTPMethod, endpoint=None, params=None, json=None, headers=None):
        """Base method for making HTTP requests."""
        url = self._build_url(endpoint, method)
        request_headers = {**self.headers, **(headers or {})}

        # Remove the API key from params since we're using Basic Auth now
        params = params or {}
        # params["key"] = self.client_secret  # Remove this line

        self._prepare_log(url, params, json, request_headers)

        try:
            response = requests.request(method.value, url, params=params, json=json, headers=request_headers)
            # response.raise_for_status()
            self.create_connection_log(
                status=str(response.json().get('meta', {}).get('status', '')) or 200,
                message=str(response.json().get('meta', {}).get('message', '')) or "Success",
                response=response.json(),
                method=method,
                payload=str(json),
            )
            return response.json()
        except Exception as e:
            self.create_connection_log(
                status=402,
                message="Error",
                response=response.text if 'response' in locals() else str(e),
                method=method,
                payload=str(json),
            )
            # Mask sensitive information in error messages
            error_message = str(e or "An Error occurred !!")
            if self.client_secret:
                error_message = error_message.replace(self.client_secret, "****")
            if self.client_id:
                error_message = error_message.replace(self.client_id, "****")
            
            frappe.throw(_("Xero API request failed: {0}").format(error_message))

        finally:
            self._log_request()
    
    def _build_url(self, endpoint, method):
        """Generate full API URL ensuring correct formatting."""
        base_url = self.base_url+ "/"  # Ensure base_url has a trailing slash
        base_path = self.BASE_PATH  # Keep BASE_PATH as-is
        endpoint = endpoint # Remove leading slash from endpoint

        # Build full URL dynamically
        full_url = "/".join(filter(None, [base_url.rstrip("/"), base_path, endpoint]))
        
        return full_url

    def _prepare_log(self, url, params, json, headers):
        self.log_data = {
            "url": url,
            "params": params,
            "request_body": json,
            "headers": self._mask_sensitive_info(headers)
        }
    
    def _log_request(self):
        if "Xero Integration" not in self.log_data:
            self.log_data["integration_request_service"] = "Xero Integration"
        enqueue(self._enqueue_log, log_data=self.log_data)
    
    def _mask_sensitive_info(self, data):
        if not isinstance(data, dict):
            return data
        sensitive_fields = {"key", "password", "token", "auth", "secret", "authorization"}
        return {k: "****" if any(s in k.lower() for s in sensitive_fields) else v for k, v in data.items()}
    
    def _enqueue_log(self, log_data):
        # Replace this with actual logging method if required
        frappe.logger().info(log_data)

    def create_connection_log(self, status, message, response=None, ref_doctype=None, method=None, ref_docname=None, payload=None):
        """Create log entry for connection test"""
        try:
            log = frappe.get_doc({
                "doctype": "Xero API Log",
                # "status": str(status),
                "message": str(message),
                "response": str(response) if response else "",
                "payload": str(payload) if payload else "",
                "api_url": self.BASE_PATH,
                "api_method": method,
                "status_code": str(status),
                "timestamp": frappe.utils.now(),
                # "reference_doctype": ref_doctype,
                # "reference_docname": ref_docname,
                "headers": str(self._mask_sensitive_info(self.headers)),
            })
            if self.enable_api_log:
                log.insert(ignore_permissions=True)
                return log
            
        except Exception as e:
            frappe.log_error(message=str(e), title="Xero Log")
            return None
