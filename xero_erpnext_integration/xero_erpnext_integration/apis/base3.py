import frappe
import requests
import base64
import json
from datetime import datetime, timedelta
from frappe.utils import now_datetime, add_to_date

class XeroBaseClient:
    """Base client for Xero API requests with automatic token management"""
    
    def __init__(self):
        self.base_url = "https://api.xero.com/api.xro/2.0"
        self.token_url = "https://identity.xero.com/connect/token"
        self.connections_url = "https://api.xero.com/connections"
        self.settings = self._get_xero_settings()
        self.access_token = None
        self.tenant_id = None
        self.token_expires_at = None
        
    def _get_xero_settings(self):
        """Get Xero settings from database"""
        try:
            return frappe.get_single("Xero Settings")
        except:
            frappe.throw("Xero Settings not found. Please configure Xero integration first.")
    
    def _get_fresh_settings_from_db(self):
        """Get fresh settings directly from database"""
        try:
            # Get settings directly from database without document loading
            settings_data = frappe.db.get_value("Xero Settings", "Xero Settings", 
                ["client_id", "client_secret", "access_token", "token_expires_at", "tenant_id", "debug_mode"], 
                as_dict=True)
            return settings_data
        except:
            frappe.throw("Xero Settings not found. Please configure Xero integration first.")
            
    def _update_db_directly(self, field_dict, doctype="Xero Settings"):
        """Update fields of a Single Doctype directly in the database."""
        try:
            for field, value in field_dict.items():
                frappe.db.sql("""
                    UPDATE `tabSingles`
                    SET `value` = %s
                    WHERE `doctype` = %s AND `field` = %s
                """, (value, doctype, field))

            frappe.db.commit()
            frappe.clear_cache(doctype=doctype)

            frappe.log_error("success", f"Updated {doctype} fields: {list(field_dict.keys())}")
            return True

        except Exception as e:
            frappe.log_error("error", f"Error updating {doctype} directly: {str(e)}")
            frappe.db.rollback()
            return False



   
    def _get_basic_auth_header(self):
        """Generate Basic Auth header using client_id and client_secret"""
        # Get fresh settings from database
        settings_data = self._get_fresh_settings_from_db()
        
        if not settings_data.get('client_id') or not settings_data.get('client_secret'):
            frappe.throw("Client ID and Client Secret are required")
        
        # Create credentials string
        credentials = f"{settings_data['client_id']}:52Hr3jJbh7z6cyKuYBX0OME3HGBrWreR98ULq-1GdAtE2Ho2"
        
        # Encode to base64
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        return f"Basic {encoded_credentials}"
    
    def _generate_access_token(self):
        """Generate access token using client credentials flow"""
        try:
            headers = {
                "Authorization": self._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "client_credentials",
                "scope": "app.connections"
            }
            
            # Get fresh settings for debug mode check
            settings_data = self._get_fresh_settings_from_db()
            
            # Log request if debug mode is enabled
            if settings_data.get('debug_mode'):
                self._log_api_call(
                    endpoint="/connect/token",
                    method="POST",
                    request_payload=data
                )
            
            response = requests.post(
                self.token_url,
                headers=headers,
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 1800)  # Default 30 minutes
                
                # Calculate expiry time (subtract 5 minutes for safety)
                self.token_expires_at = add_to_date(
                    now_datetime(), 
                    seconds=expires_in - 300
                )
                
                # Update database directly
                # frappe.db.set_value("Xero Settings", None, "access_token", self.access_token, update_modified=False)
                # frappe.db.set_value("Xero Settings", None, "token_expires_at", self.token_expires_at, update_modified=False)
                # frappe.clear_cache(doctype="Xero Settings")

                update_success = self._update_db_directly({
                    "access_token": self.access_token,
                    "token_expires_at": self.token_expires_at,
                })
                

                
                if not update_success:
                    frappe.log_error("warning:","Failed to save token to database, but token is valid in memory")

                # Get tenant ID if not already set
                # if not settings_data.get('tenant_id'):
                #     self._get_tenant_id(self.access_token)
                
                # Log successful response
                if settings_data.get('debug_mode'):
                    self._log_api_call(
                        endpoint="/connect/token",
                        method="POST",
                        response_body=response.json(),
                        status_code=200
                    )
                
                frappe.log_error("success:","Xero access token generated successfully")
                return True
                
            else:
                error_msg = f"Failed to generate access token: {response.status_code} - {response.text}"
                
                # Log error
                if settings_data.get('debug_mode'):
                    self._log_api_call(
                        endpoint="/connect/token",
                        method="POST",
                        response_body=response.text,
                        status_code=response.status_code,
                        error_message=error_msg
                    )
                
                frappe.log_error("error:",error_msg)
                frappe.throw(error_msg)
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error while generating access token: {str(e)}"
            frappe.log_error("error:",error_msg)
            frappe.throw(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error while generating access token: {str(e)}"
            frappe.log_error("error:",error_msg)
            frappe.throw(error_msg)

    def _get_tenant_id(self, access_token):
        """Get tenant ID from Xero connections"""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                self.connections_url,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                connections = response.json()
                if connections and len(connections) > 0:
                    self.tenant_id = connections[0].get("tenantId")
                    
                    # Update database directly
                    update_success = self._update_db_directly({
                        "tenant_id": self.tenant_id
                    })
                    
                    if not update_success:
                        frappe.log_error("Tenant Error:", "Failed to save tenant_id to database, but tenant_id is valid in memory")

                    frappe.log_error("Tenant Error:", f"Tenant ID retrieved: {self.tenant_id}")
                else:
                    frappe.throw("No Xero connections found")
            else:
                frappe.throw(f"Failed to get tenant ID: {response.status_code} - {response.text}")
                
        except Exception as e:
            frappe.log_error("Tenant Error:",f"Error getting tenant ID: {str(e)}")
            # Don't throw here as tenant ID might be manually set
    
    def _is_token_expired(self):
        """Check if access token is expired"""
        if not self.access_token or not self.token_expires_at:
            return True
        
        # Convert token_expires_at to datetime if it's a string
        if isinstance(self.token_expires_at, str):
            from frappe.utils import get_datetime
            try:
                expires_at = get_datetime(self.token_expires_at)
            except:
                # If conversion fails, consider token expired
                return True
        else:
            expires_at = self.token_expires_at
        
        return now_datetime() >= expires_at

    def _ensure_valid_token(self):
        """Ensure we have a valid access token"""
        # Get fresh settings from database
        settings_data = self._get_fresh_settings_from_db()
        
        # Load token info from database
        if settings_data.get('access_token') and settings_data.get('token_expires_at'):
            self.access_token = settings_data['access_token']
            self.token_expires_at = settings_data['token_expires_at']
        
        # Check if token is expired or missing
        if self._is_token_expired():
            frappe.log_error("success:","Access token expired or missing, generating new token")
            self._generate_access_token()
        
        # Set tenant ID from database
        if settings_data.get('access_token'):
            self.access_token = settings_data['access_token']
    
    def make_request(self, method, endpoint, data=None, params=None):
        """
        Make authenticated request to Xero API
        
        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE)
            endpoint (str): API endpoint (e.g., '/Invoices')
            data (dict): Request payload for POST/PUT requests
            params (dict): Query parameters
            
        Returns:
            dict: Response data
        """
        # Ensure we have a valid token
        self._ensure_valid_token()
        
        if not self.access_token:
            frappe.throw("Tenant ID not found. Please check Xero connection.")
        
        # Prepare request
        url = f"{self.base_url}{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            # "Xero-tenant-id": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            # Get fresh settings for debug mode check
            settings_data = self._get_fresh_settings_from_db()
            
            # Log request if debug mode is enabled
            if settings_data.get('debug_mode'):
                self._log_api_call(
                    endpoint=endpoint,
                    method=method,
                    request_payload=data or params
                )
            
            # Make request
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                frappe.throw(f"Unsupported HTTP method: {method}")
            
            # Handle response
            if response.status_code in [200, 201]:
                response_data = response.json() if response.content else {}
                
                # Log successful response
                if settings_data.get('debug_mode'):
                    self._log_api_call(
                        endpoint=endpoint,
                        method=method,
                        response_body=response_data,
                        status_code=response.status_code
                    )
                
                return response_data
                
            elif response.status_code == 401:
                # Token might be expired, try to regenerate once
                frappe.log_error("warning:","Received 401, attempting to regenerate token")
                self._generate_access_token()
                
                # Retry the request once with new token
                headers["Authorization"] = f"Bearer {self.access_token}"
                
                if method.upper() == "GET":
                    response = requests.get(url, headers=headers, params=params, timeout=30)
                elif method.upper() == "POST":
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                elif method.upper() == "PUT":
                    response = requests.put(url, headers=headers, json=data, timeout=30)
                elif method.upper() == "DELETE":
                    response = requests.delete(url, headers=headers, timeout=30)
                
                if response.status_code in [200, 201]:
                    response_data = response.json() if response.content else {}
                    
                    settings_data = self._get_fresh_settings_from_db()
                    if settings_data.get('debug_mode'):
                        self._log_api_call(
                            endpoint=endpoint,
                            method=method,
                            response_body=response_data,
                            status_code=response.status_code
                        )
                    
                    return response_data
                else:
                    error_msg = f"Request failed after token refresh: {response.status_code} - {response.text}"
                    self._handle_error(endpoint, method, response, error_msg)
            else:
                error_msg = f"Request failed: {response.status_code} - {response.text}"
                self._handle_error(endpoint, method, response, error_msg)
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {str(e)}"
            self._handle_error(endpoint, method, None, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self._handle_error(endpoint, method, None, error_msg)
    
    def _handle_error(self, endpoint, method, response, error_msg):
        """Handle API errors"""
        status_code = response.status_code if response else 500
        response_text = response.text if response else ""
        
        # Get fresh settings for debug mode check
        settings_data = self._get_fresh_settings_from_db()
        
        # Log error
        if settings_data.get('debug_mode'):
            self._log_api_call(
                endpoint=endpoint,
                method=method,
                response_body=response_text,
                status_code=status_code,
                error_message=error_msg
            )
        
        frappe.log_error("error:",f"Xero API Error: {error_msg}")
        frappe.throw(error_msg)
    
    def _log_api_call(self, endpoint, method, request_payload=None, response_body=None, status_code=None, error_message=None):
        """Log API call for debugging"""
        try:
            frappe.get_doc({
                "doctype": "Xero API Log",
                "api_url": endpoint,
                "api_method": method,
                "payload": json.dumps(request_payload) if request_payload else None,
                "response": json.dumps(response_body) if response_body else None,
                "status_code": status_code,
                "message": error_message,
                "timestamp": now_datetime()
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error("error:",f"Failed to log API call: {str(e)}")
    
    def test_connection(self):
        """Test the Xero API connection"""
        try:
            response = self.make_request("GET", "/Invoices")
            return {
                    "status": "success",
                    "message": f"Connection test successful {response.json()}"
                }
            
            
            # if response:
            #     # org = response["Organisations"][0]
            #     return {
            #         "status": "success",
            #         "message": f"Successfully connected to Xero",
            #         # "organisation": org.get("Name"),
            #         # "country": org.get("CountryCode"),
            #         # "currency": org.get("BaseCurrency")
            #     }
            # else:
            #     return {
            #         "status": "error",
            #         "message": "No organisation data received"
            #     }
                
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

# Singleton instance
_xero_client = None

def get_xero_client():
    """Get singleton Xero client instance"""
    global _xero_client
    if _xero_client is None:
        _xero_client = XeroBaseClient()
    return _xero_client
