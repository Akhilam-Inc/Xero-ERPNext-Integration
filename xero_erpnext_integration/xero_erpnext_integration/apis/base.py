import requests
import frappe
import base64
from urllib.parse import urljoin
from enum import Enum
from frappe import _
from frappe.utils.background_jobs import enqueue
from datetime import datetime, timedelta
import json

class SupportedHTTPMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"

class XeroAPIClient:
    """
    Xero API Client for OAuth 2.0 authentication and API calls
    """
    
    def __init__(self):
        self.settings = frappe.get_single("Xero Settings")
        self.base_url = "https://api.xero.com/api.xro/2.0"
        self.auth_url = "https://login.xero.com/identity/connect/authorize"
        self.token_url = self.settings.access_token_url
        self.connections_url = "https://api.xero.com/connections"
        
        # OAuth 2.0 settings
        self.client_id = self.settings.client_id
        self.client_secret = self.settings.client_secret
        self.redirect_uri = self.settings.redirect_uri
        self.scope = "accounting.transactions accounting.contacts accounting.settings offline_access"
        
        # Current session tokens
        self.access_token = self.settings.access_token
        self.refresh_token = self.settings.refresh_token
        self.tenant_id = self.settings.tenant_id
        
        # Initialize headers
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.access_token:
            self.headers["Authorization"] = f"Bearer {self.access_token}"
        
        if self.tenant_id:
            self.headers["Xero-Tenant-Id"] = self.tenant_id
    
    def get_authorization_url(self, state=None):
        """Generate OAuth 2.0 authorization URL"""
        try:
            if not self.client_id or not self.redirect_uri:
                frappe.throw(_("Client ID and Redirect URI are required"))
            
            params = {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.scope,
                "state": state or frappe.generate_hash(length=10)
            }
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            return f"{self.auth_url}?{query_string}"
            
        except Exception as e:
            frappe.log_error(f"Failed to generate authorization URL: {str(e)}", "Xero Auth URL")
            raise
    
    def exchange_code_for_token(self, state=None):
        """Exchange authorization code for access token"""
        try:
            # Prepare token request
            token_data = {
                "grant_type": "authorization_code",
                # "client_id": self.client_id,
                "code": self.settings.code,
                "redirect_uri": self.redirect_uri
            }
            
            # Create basic auth header
            auth_header = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Make token request
            response = requests.post(self.token_url, data=token_data, headers=headers)
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Save tokens to settings
                self.settings.access_token = token_data.get("access_token")
                self.settings.refresh_token = token_data.get("refresh_token")
                # self.settings.scope = token_data.get("scope")
                
                # Calculate expiry time
                expires_in = token_data.get("expires_in", 1800)  # Default 30 minutes
                expires_at = datetime.now() + timedelta(seconds=expires_in)
                self.settings.token_expires_at = expires_at
                
                # Get tenant information
                self._get_and_save_tenant_info()
                
                # Save settings
                self.settings.save()
                
                return True
            else:
                error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
                frappe.log_error(error_msg, "Xero Token Exchange")
                return False
                
        except Exception as e:
            frappe.log_error(f"Token exchange error: {str(e)}", "Xero Token Exchange")
            return False
    
    def _get_and_save_tenant_info(self):
        """Get tenant information and save to settings"""
        try:
            # Update headers with new access token
            self.access_token = self.settings.access_token
            self.headers["Authorization"] = f"Bearer {self.access_token}"
            
            # Get connections (tenants)
            response = requests.get(self.connections_url, headers=self.headers)
            
            if response.status_code == 200:
                connections = response.json()
                
                if connections and len(connections) > 0:
                    # Use first connection as default
                    connection = connections[0]
                    self.settings.tenant_id = connection.get("tenantId")
                    self.settings.tenant_name = connection.get("tenantName")
                    
                    # Update headers
                    self.headers["Xero-Tenant-Id"] = self.settings.tenant_id
                    
        except Exception as e:
            frappe.log_error(f"Failed to get tenant info: {str(e)}", "Xero Tenant Info")
    
    def refresh_access_token(self):
        """Refresh access token using refresh token"""
        try:
            if not self.refresh_token:
                return False
            
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token
            }
            
            auth_header = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            response = requests.post(self.token_url, data=token_data, headers=headers)
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Update tokens
                self.settings.access_token = token_data.get("access_token")
                if token_data.get("refresh_token"):
                    self.settings.refresh_token = token_data.get("refresh_token")
                
                # Update expiry
                expires_in = token_data.get("expires_in", 1800)
                expires_at = datetime.now() + timedelta(seconds=expires_in)
                self.settings.token_expires_at = expires_at
                
                # Save settings
                self.settings.save()
                
                # Update headers
                self.access_token = self.settings.access_token
                self.headers["Authorization"] = f"Bearer {self.access_token}"
                
                return True
            else:
                frappe.log_error(f"Token refresh failed: {response.text}", "Xero Token Refresh")
                return False
                
        except Exception as e:
            frappe.log_error(f"Token refresh error: {str(e)}", "Xero Token Refresh")
            return False
    
    def _ensure_valid_token(self):
        """Ensure we have a valid access token"""
        if not self.access_token:
            frappe.throw(_("No access token available. Please authorize the application."))
        
        # Check if token is expired
        if self.settings.token_expires_at:
            expires_at = self.settings.token_expires_at
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            
            # Refresh if expires in next 5 minutes
            if datetime.now() >= expires_at - timedelta(minutes=5):
                if not self.refresh_access_token():
                    frappe.throw(_("Failed to refresh access token. Please re-authorize the application."))
    
    def make_request(self, method, endpoint, data=None, params=None):
        """Make authenticated request to Xero API"""
        try:
            # Ensure valid token
            self._ensure_valid_token()
            
            # Build URL
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
            
            # Prepare request
            request_headers = self.headers.copy()
            
            # Log request
            self._log_request(method, url, data, params)
            
            # Make request
            if method.upper() == "GET":
                response = requests.get(url, headers=request_headers, params=params)
            elif method.upper() == "POST":
                response = requests.post(url, headers=request_headers, json=data, params=params)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=request_headers, json=data, params=params)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=request_headers, params=params)
            else:
                frappe.throw(_("Unsupported HTTP method: {0}").format(method))
            
            # Log response
            self._log_response(response)
            
            # Handle response
            if response.status_code in [200, 201]:
                try:
                    return response.json()
                except:
                    return {"message": "Success", "data": response.text}
            elif response.status_code == 401:
                # Try to refresh token and retry once
                if self.refresh_access_token():
                    request_headers["Authorization"] = f"Bearer {self.access_token}"
                    
                    # Retry request
                    if method.upper() == "GET":
                        response = requests.get(url, headers=request_headers, params=params)
                    elif method.upper() == "POST":
                        response = requests.post(url, headers=request_headers, json=data, params=params)
                    elif method.upper() == "PUT":
                        response = requests.put(url, headers=request_headers, json=data, params=params)
                    elif method.upper() == "DELETE":
                        response = requests.delete(url, headers=request_headers, params=params)
                    
                    if response.status_code in [200, 201]:
                        try:
                            return response.json()
                        except:
                            return {"message": "Success", "data": response.text}
                
                frappe.throw(_("Authentication failed. Please re-authorize the application."))
            else:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                frappe.throw(_(error_msg))
                
        except Exception as e:
            frappe.log_error(f"API request failed: {str(e)}", "Xero API Request")
            raise
    
    def test_connection(self):
        """Test connection to Xero API"""
        try:
            if not self.settings.enable:
                return {"status": "error", "message": "Xero integration is not enabled"}
            
            if not self.access_token:
                return {"status": "error", "message": "No access token. Please authorize the application first."}
            
            if not self.tenant_id:
                return {"status": "error", "message": "No tenant selected. Please complete authorization."}
            
            # Test API call - get organisation info
            response = self.make_request("GET", "Organisation")
            
            if response and "Organisations" in response:
                org = response["Organisations"][0] if response["Organisations"] else {}
                return {
                    "status": "success",
                    "message": "Connection successful",
                    "organisation": {
                        "name": org.get("Name"),
                        "country_code": org.get("CountryCode"),
                        "currency_code": org.get("BaseCurrency")
                    }
                }
            else:
                return {"status": "error", "message": "Failed to retrieve organisation information"}
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_contacts(self, contact_name=None):
        """Get contacts from Xero"""
        try:
            params = {}
            if contact_name:
                params["where"] = f'Name=="{contact_name}"'
            
            response = self.make_request("GET", "Contacts", params=params)
            return response.get("Contacts", []) if response else []
            
        except Exception as e:
            frappe.log_error(f"Failed to get contacts: {str(e)}", "Xero Get Contacts")
            return []
    
    def create_contact(self, contact_data):
        """Create contact in Xero"""
        try:
            data = {"Contacts": [contact_data]}
            response = self.make_request("POST", "Contacts", data=data)
            
            if response and "Contacts" in response:
                return response["Contacts"][0]
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to create contact: {str(e)}", "Xero Create Contact")
            return None
    
    def create_invoice(self, invoice_data):
        """Create invoice in Xero"""
        try:
            data = {"Invoices": [invoice_data]}
            response = self.make_request("POST", "Invoices", data=data)
            
            if response and "Invoices" in response:
                return response["Invoices"][0]
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to create invoice: {str(e)}", "Xero Create Invoice")
            return None
    
    def get_invoice(self, invoice_id):
        """Get invoice from Xero"""
        try:
            response = self.make_request("GET", f"Invoices/{invoice_id}")
            
            if response and "Invoices" in response:
                return response["Invoices"][0]
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to get invoice: {str(e)}", "Xero Get Invoice")
            return None
    
    def get_payments(self, invoice_id=None):
        """Get payments from Xero"""
        try:
            params = {}
            if invoice_id:
                params["where"] = f'Invoice.InvoiceID==Guid("{invoice_id}")'
            
            response = self.make_request("GET", "Payments", params=params)
            return response.get("Payments", []) if response else []
            
        except Exception as e:
            frappe.log_error(f"Failed to get payments: {str(e)}", "Xero Get Payments")
            return []
    
    def _log_request(self, method, url, data, params):
        """Log API request"""
        if not self.settings.debug_mode:
            return
        
        try:
            log_data = {
                "doctype": "Xero API Log",
                "api_method": method,
                "api_endpoint": url,
                "request_payload": json.dumps({
                    "data": data,
                    "params": params
                }, indent=2) if (data or params) else "",
                "timestamp": frappe.utils.now(),
                "tenant_id": self.tenant_id
            }
            
            frappe.get_doc(log_data).insert(ignore_permissions=True)
            
        except Exception as e:
            frappe.log_error(f"Failed to log request: {str(e)}", "Xero Request Log")
    
    def _log_response(self, response):
        """Log API response"""
        if not self.settings.debug_mode:
            return
        
        try:
            # Find the most recent log entry to update
            logs = frappe.get_all("Xero API Log", 
                                filters={"tenant_id": self.tenant_id},
                                order_by="creation desc",
                                limit=1)
            
            if logs:
                log_doc = frappe.get_doc("Xero API Log", logs[0].name)
                log_doc.status_code = str(response.status_code)
                log_doc.message = "Success" if response.status_code < 400 else "Error"
                
                try:
                    log_doc.response_data = json.dumps(response.json(), indent=2)
                except:
                    log_doc.response_data = response.text
                
                log_doc.save(ignore_permissions=True)
                
        except Exception as e:
            frappe.log_error(f"Failed to log response: {str(e)}", "Xero Response Log")


# Utility function to get Xero client
@frappe.whitelist()
def get_xero_client():
    """Get configured Xero API client"""
    return XeroAPIClient()


