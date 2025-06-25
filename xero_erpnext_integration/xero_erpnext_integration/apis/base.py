import requests
import frappe
import base64
from urllib.parse import urljoin
from enum import Enum
from frappe import _
from frappe.utils.background_jobs import enqueue
from datetime import datetime, timedelta

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
        self.access_token_url = self.config.access_token  # Base URL for access token API
        self.enabled = self.config.enable,
        self.enable_api_log = self.config.debug_mode
        self.client_id = self.config.ccid
        
        # Initialize headers - will be updated with bearer token
        self.headers = {
            "Content-Type": "application/json"
        }
        self.log_data = {}
        
        if self.enabled:
            self.validate_credentials()
            # Get access token and set bearer token in headers
            self._set_bearer_token()
        else:
            frappe.throw(_("Please enable <strong>Xero</strong> integration."), title=_("Integration Disabled"))

    def validate_credentials(self):
        if not self.client_secret:
            frappe.throw(_("Please set <strong>Xero</strong> API key."), title=_("API Key Is Missing"))
        
        if not self.client_id:
            frappe.throw(_("Please set <strong>Xero</strong> Client ID."), title=_("Client ID Is Missing"))
            
        if not self.access_token_url:
            frappe.throw(_("Please set <strong>Xero</strong> Access Token URL."), title=_("Access Token URL Is Missing"))

    def _create_basic_auth_header(self):
        """Create Basic Authentication header for access token request"""
        if not self.client_id or not self.client_secret:
            return ""
        
        # Create the credentials string: client_id:client_secret
        credentials = f"{self.client_id}:{self.client_secret}"
        
        # Encode to base64
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        
        # Return the Basic Auth header
        return f"Basic {encoded_credentials}"

    def _get_access_token(self):
        """Get access token using client credentials"""
        try:
            # Check if we have a valid cached token
            cached_token = self._get_cached_token()
            if cached_token:
                return cached_token
            
            # Prepare headers for token request
            token_headers = {
                "Authorization": self._create_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Prepare data for token request (OAuth 2.0 client credentials flow)
            token_data = {
                "grant_type": "client_credentials",
                "scope": "app.connections"  # Adjust scopes as needed
            }
            
            # Make request to get access token
            response = requests.post(
                self.access_token_url,
                headers=token_headers,
                data=token_data
            )
            
            if response.status_code == 200:
                token_response = response.json()
                access_token = token_response.get('access_token')
                expires_in = token_response.get('expires_in', 3600)  # Default to 1 hour
                
                if access_token:
                    # Cache the token
                    self._cache_token(access_token, expires_in)
                    return access_token
                else:
                    frappe.throw(_("Access token not found in response"))
            else:
                error_msg = f"Failed to get access token. Status: {response.status_code}, Response: {response.text}"
                frappe.throw(_(error_msg))
                
        except Exception as e:
            error_message = str(e)
            # Mask sensitive information
            if self.client_secret:
                error_message = error_message.replace(self.client_secret, "****")
            if self.client_id:
                error_message = error_message.replace(self.client_id, "****")
            
            frappe.throw(_("Failed to get Xero access token: {0}").format(error_message))

    def _get_cached_token(self):
        """Get cached access token if still valid"""
        try:
            # Try to get cached token from database or cache
            cache_key = f"xero_access_token_{self.client_id}"
            cached_data = frappe.cache().get_value(cache_key)
            
            if cached_data:
                token_data = frappe.parse_json(cached_data)
                expires_at = datetime.fromisoformat(token_data.get('expires_at'))
                
                # Check if token is still valid (with 5 minute buffer)
                if datetime.now() < expires_at - timedelta(minutes=5):
                    return token_data.get('access_token')
            
            return None
        except Exception:
            return None

    def _cache_token(self, access_token, expires_in):
        """Cache the access token"""
        try:
            cache_key = f"xero_access_token_{self.client_id}"
            expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            token_data = {
                'access_token': access_token,
                'expires_at': expires_at.isoformat()
            }
            
            # Cache for the duration of the token
            frappe.cache().set_value(cache_key, frappe.as_json(token_data), expires_in)
        except Exception as e:
            frappe.log_error(f"Failed to cache access token: {str(e)}", "Xero Token Cache")

    def _set_bearer_token(self):
        """Get access token and set it in headers"""
        access_token = self._get_access_token()
        if access_token:
            self.headers["Authorization"] = f"Bearer {access_token}"
        else:
            frappe.throw(_("Failed to obtain Xero access token"))

    def _refresh_token_if_needed(self):
        """Refresh token if it's expired or about to expire"""
        try:
            cache_key = f"xero_access_token_{self.client_id}"
            cached_data = frappe.cache().get_value(cache_key)
            
            if cached_data:
                token_data = frappe.parse_json(cached_data)
                expires_at = datetime.fromisoformat(token_data.get('expires_at'))
                
                # Refresh if token expires in less than 5 minutes
                if datetime.now() >= expires_at - timedelta(minutes=5):
                    self._set_bearer_token()
            else:
                # No cached token, get a new one
                self._set_bearer_token()
        except Exception:
            # If anything goes wrong, try to get a fresh token
            self._set_bearer_token()

    def get(self, endpoint=None, params=None, headers=None):
        return self._make_request(SupportedHTTPMethod.GET, endpoint=endpoint, params=params, headers=headers)
    
    def delete(self, endpoint=None, params=None, headers=None):
        return self._make_request(SupportedHTTPMethod.DELETE, endpoint=endpoint, params=params, headers=headers)
    
    def post(self, endpoint, params=None, json=None, headers=None):
        return self._make_request(SupportedHTTPMethod.POST, endpoint, params=params, json=json, headers=headers)

    def put(self, endpoint, json=None, headers=None):
        return self._make_request(SupportedHTTPMethod.PUT, endpoint, json=json, headers=headers)

    def _make_request(self, method: SupportedHTTPMethod, endpoint=None, params=None, json=None, headers=None):
        """Base method for making HTTP requests."""
        # Refresh token if needed before making the request
        self._refresh_token_if_needed()
        
        url = self._build_url(endpoint, method)
        request_headers = {**self.headers, **(headers or {})}

        # Remove API key from params since we're using Bearer token
        params = params or {}

        self._prepare_log(url, params, json, request_headers)

        try:
            response = requests.request(method.value, url, params=params, json=json, headers=request_headers)
            
            # Handle token expiration (401 Unauthorized)
            if response.status_code == 401:
                # Token might be expired, try to refresh and retry once
                self._set_bearer_token()
                request_headers = {**self.headers, **(headers or {})}
                response = requests.request(method.value, url, params=params, json=json, headers=request_headers)
            
            # Try to parse JSON response
            try:
                response_json = response.json()
            except:
                response_json = {"message": response.text, "status_code": response.status_code}
            
            self.create_connection_log(
                status=str(response_json.get('meta', {}).get('status', '')) or response.status_code,
                message=str(response_json.get('meta', {}).get('message', '')) or "Success" if response.status_code < 400 else "Error",
                response=response_json,
                method=method,
                payload=str(json),
            )
            
            if response.status_code >= 400:
                frappe.throw(_("Xero API request failed with status {0}: {1}").format(response.status_code, response.text))
            
            return response_json
            
        except Exception as e:
            error_response = response.text if 'response' in locals() else str(e)
            self.create_connection_log(
                status=getattr(response, 'status_code', 500) if 'response' in locals() else 500,
                message="Error",
                response=error_response,
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
        base_url = self.base_url + "/"  # Ensure base_url has a trailing slash
        base_path = self.BASE_PATH  # Keep BASE_PATH as-is
        endpoint = endpoint  # Remove leading slash from endpoint

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
        sensitive_fields = {"key", "password", "token", "auth", "secret", "authorization", "bearer"}
        return {k: "****" if any(s in k.lower() for s in sensitive_fields) else v for k, v in data.items()}
    
    def _enqueue_log(self, log_data):
        # Replace this with actual logging method if required
        frappe.logger().info(log_data)

    def create_connection_log(self, status, message, response=None, ref_doctype=None, method=None, ref_docname=None, payload=None):
        """Create log entry for connection test"""
        try:
            log = frappe.get_doc({
                "doctype": "Xero API Log",
                "message": str(message),
                "response": str(response) if response else "",
                "payload": str(payload) if payload else "",
                "api_url": self.BASE_PATH,
                "api_method": str(method.value) if method else "",
                "status_code": str(status),
                "timestamp": frappe.utils.now(),
                "headers": str(self._mask_sensitive_info(self.headers)),
            })
            if self.enable_api_log:
                log.insert(ignore_permissions=True)
                return log
            
        except Exception as e:
            frappe.log_error(message=str(e), title="Xero Log")
            return None
