import frappe
import json
from datetime import datetime, timedelta
from frappe import _
from frappe.utils import now, get_datetime
from frappe.utils.background_jobs import enqueue
from xero_python.api_client import ApiClient, Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.exceptions import AccountingBadRequestException, ApiException
import logging

class XeroAPIClient:
    """
    Xero API Client using official Xero Python SDK
    Handles OAuth2 authentication, token management, and API calls
    """
    
    def __init__(self):
        self.settings = frappe.get_single("Xero Settings")
        self.validate_settings()
        
        # Initialize configuration
        self.configuration = Configuration(
            debug=self.settings.debug_mode,
            oauth2_token=self._get_stored_token()
        )
        
        # Initialize API client
        self.api_client = ApiClient(
            configuration=self.configuration,
            pool_threads=1
        )
        
        # Initialize API instances
        self.accounting_api = AccountingApi(self.api_client)
        self.identity_api = IdentityApi(self.api_client)
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
    def validate_settings(self):
        """Validate Xero Settings configuration"""
        if not self.settings.enable:
            frappe.throw(_("Xero integration is not enabled"), title=_("Integration Disabled"))
            
        required_fields = {
            'client_id': 'Client ID',
            'client_secret': 'Client Secret',
            'redirect_uri': 'Redirect URI'
        }
        
        for field, label in required_fields.items():
            if not getattr(self.settings, field, None):
                frappe.throw(_("Please configure {0} in Xero Settings").format(label), 
                           title=_("Configuration Missing"))
    
    def _get_stored_token(self):
        """Get stored OAuth2 token from Xero Settings"""
        try:
            if not self.settings.access_token:
                return None
                
            token_data = {
                'access_token': self.settings.get_password('access_token'),
                'refresh_token': self.settings.get_password('refresh_token'),
                'expires_at': self.settings.token_expires_at,
                'scope': self.settings.scope or []
            }
            
            # Check if token is expired
            if self.settings.token_expires_at:
                expires_at = get_datetime(self.settings.token_expires_at)
                if datetime.now() >= expires_at:
                    # Token expired, try to refresh
                    return self._refresh_token()
            
            return OAuth2Token(
                access_token=token_data['access_token'],
                refresh_token=token_data['refresh_token'],
                expires_at=token_data['expires_at'],
                scope=token_data['scope']
            )
            
        except Exception as e:
            self._log_error("Error getting stored token", str(e))
            return None
    
    def _refresh_token(self):
        """Refresh OAuth2 token"""
        try:
            if not self.settings.refresh_token:
                frappe.throw(_("No refresh token available. Please re-authorize."))
            
            # Create temporary client for token refresh
            temp_config = Configuration()
            temp_client = ApiClient(temp_config)
            
            # Refresh token
            new_token = temp_client.refresh_oauth2_token(
                client_id=self.settings.client_id,
                client_secret=self.settings.get_password('client_secret'),
                refresh_token=self.settings.get_password('refresh_token')
            )
            
            # Update stored token
            self._store_token(new_token)
            
            return new_token
            
        except Exception as e:
            self._log_error("Token refresh failed", str(e))
            frappe.throw(_("Failed to refresh token: {0}").format(str(e)))
    
    def _store_token(self, token):
        """Store OAuth2 token in Xero Settings"""
        try:
            self.settings.access_token = token.access_token
            self.settings.refresh_token = token.refresh_token
            self.settings.token_expires_at = token.expires_at
            self.settings.scope = json.dumps(token.scope) if token.scope else None
            self.settings.save(ignore_permissions=True)
            
        except Exception as e:
            self._log_error("Error storing token", str(e))
    
    def get_authorization_url(self, state=None):
        """Get OAuth2 authorization URL"""
        try:
            scopes = [
                "accounting.transactions",
                "accounting.contacts", 
                "accounting.settings",
                "accounting.attachments"
            ]
            
            auth_url = self.api_client.build_authorization_url(
                redirect_uri=self.settings.redirect_uri,
                scopes=scopes,
                state=state
            )
            
            return auth_url
            
        except Exception as e:
            self._log_error("Error building authorization URL", str(e))
            raise
    
    def exchange_code_for_token(self, auth_code, state=None):
        """Exchange authorization code for access token"""
        try:
            token = self.api_client.get_oauth2_token(
                client_id=self.settings.client_id,
                client_secret=self.settings.get_password('client_secret'),
                code=auth_code,
                redirect_uri=self.settings.redirect_uri
            )
            
            # Store token
            self._store_token(token)
            
            # Get tenant connections
            self._fetch_tenant_connections()
            
            return token
            
        except Exception as e:
            self._log_error("Token exchange failed", str(e))
            raise
    
    def _fetch_tenant_connections(self):
        """Fetch and store tenant connections"""
        try:
            connections = self.identity_api.get_connections()
            
            if connections:
                # Store first tenant as default
                first_tenant = connections[0]
                self.settings.tenant_id = first_tenant.tenant_id
                self.settings.tenant_name = first_tenant.tenant_name
                self.settings.save(ignore_permissions=True)
                
                # Log available tenants
                self._create_api_log(
                    "GET", 
                    "/connections", 
                    200, 
                    "Success", 
                    response_data={"connections": len(connections)}
                )
                
        except Exception as e:
            self._log_error("Error fetching tenant connections", str(e))
    
    def test_connection(self):
        """Test connection to Xero API"""
        try:
            if not self.settings.tenant_id:
                return {
                    "status": "error",
                    "message": "No tenant configured. Please complete OAuth authorization."
                }
            
            # Test by getting organisation info
            organisations = self.accounting_api.get_organisations(
                xero_tenant_id=self.settings.tenant_id
            )
            
            if organisations and organisations.organisations:
                org = organisations.organisations[0]
                
                self._create_api_log(
                    "GET", 
                    "/organisations", 
                    200, 
                    "Connection test successful"
                )
                
                return {
                    "status": "success",
                    "message": f"Connected to {org.name}",
                    "organisation": {
                        "name": org.name,
                        "country_code": org.country_code,
                        "currency_code": org.base_currency
                    }
                }
            else:
                return {
                    "status": "error", 
                    "message": "No organisation data received"
                }
                
        except AccountingBadRequestException as e:
            error_msg = self._parse_xero_error(e)
            self._create_api_log("GET", "/organisations", 400, error_msg)
            return {"status": "error", "message": error_msg}
            
        except ApiException as e:
            error_msg = f"API Error: {e.status} - {e.reason}"
            self._create_api_log("GET", "/organisations", e.status, error_msg)
            return {"status": "error", "message": error_msg}
            
        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            self._log_error("Connection test failed", error_msg)
            return {"status": "error", "message": error_msg}
    
    def get_contacts(self, contact_name=None, contact_number=None):
        """Get contacts from Xero"""
        try:
            where_clause = None
            if contact_name:
                where_clause = f'Name=="{contact_name}"'
            elif contact_number:
                where_clause = f'ContactNumber=="{contact_number}"'
            
            contacts = self.accounting_api.get_contacts(
                xero_tenant_id=self.settings.tenant_id,
                where=where_clause
            )
            
            self._create_api_log(
                "GET", 
                "/contacts", 
                200, 
                f"Retrieved {len(contacts.contacts) if contacts.contacts else 0} contacts"
            )
            
            return contacts.contacts if contacts else []
            
        except Exception as e:
            self._log_error("Error getting contacts", str(e))
            return []
    
    def create_contact(self, contact_data):
        """Create contact in Xero"""
        try:
            from xero_python.accounting.model.contact import Contact
            from xero_python.accounting.model.contacts import Contacts
            
            contact = Contact(**contact_data)
            contacts = Contacts(contacts=[contact])
            
            result = self.accounting_api.create_contacts(
                xero_tenant_id=self.settings.tenant_id,
                contacts=contacts
            )
            
            self._create_api_log(
                "POST", 
                "/contacts", 
                200, 
                "Contact created successfully",
                request_data=contact_data
            )
            
            return result.contacts[0] if result.contacts else None
            
        except Exception as e:
            self._log_error("Error creating contact", str(e))
            raise
    
    def create_invoice(self, invoice_data):
        """Create invoice in Xero"""
        try:
            from xero_python.accounting.model.invoice import Invoice
            from xero_python.accounting.model.invoices import Invoices
            
            invoice = Invoice(**invoice_data)
            invoices = Invoices(invoices=[invoice])
            
            result = self.accounting_api.create_invoices(
                xero_tenant_id=self.settings.tenant_id,
                invoices=invoices
            )
            
            self._create_api_log(
                "POST", 
                "/invoices", 
                200, 
                "Invoice created successfully",
                request_data=invoice_data
            )
            
            return result.invoices[0] if result.invoices else None
            
        except AccountingBadRequestException as e:
            error_msg = self._parse_xero_error(e)
            self._create_api_log("POST", "/invoices", 400, error_msg, request_data=invoice_data)
            raise frappe.ValidationError(error_msg)
            
        except Exception as e:
            self._log_error("Error creating invoice", str(e))
            raise
    
    def get_invoice(self, invoice_id):
        """Get invoice from Xero"""
        try:
            invoice = self.accounting_api.get_invoice(
                xero_tenant_id=self.settings.tenant_id,
                invoice_id=invoice_id
            )
            
            return invoice.invoices[0] if invoice.invoices else None
            
        except Exception as e:
            self._log_error("Error getting invoice", str(e))
            return None
    
    def get_payments(self, invoice_id=None):
        """Get payments from Xero"""
        try:
            where_clause = None
            if invoice_id:
                where_clause = f'Invoice.InvoiceID==Guid("{invoice_id}")'
            
            payments = self.accounting_api.get_payments(
                xero_tenant_id=self.settings.tenant_id,
                where=where_clause
            )
            
            return payments.payments if payments else []
            
        except Exception as e:
            self._log_error("Error getting payments", str(e))
            return []
    
    def _parse_xero_error(self, exception):
        """Parse Xero API error response"""
        try:
            if hasattr(exception, 'body') and exception.body:
                error_data = json.loads(exception.body)
                if 'Elements' in error_data:
                    errors = []
                    for element in error_data['Elements']:
                        if 'ValidationErrors' in element:
                            for error in element['ValidationErrors']:
                                errors.append(error.get('Message', 'Unknown error'))
                    return '; '.join(errors) if errors else 'Validation failed'
                elif 'Message' in error_data:
                    return error_data['Message']
            
            return f"Xero API Error: {exception.status} - {exception.reason}"
            
        except:
            return f"Xero API Error: {exception.status} - {exception.reason}"
    
    def _create_api_log(self, method, endpoint, status_code, message, request_data=None, response_data=None):
        """Create API log entry"""
        try:
            if not self.settings.debug_mode:
                return
                
            log_doc = frappe.get_doc({
                "doctype": "Xero API Log",
                "api_method": method,
                "api_url": endpoint,
                "status_code": status_code,
                "message": message,
                "payload": json.dumps(request_data, indent=2) if request_data else "",
                "response": json.dumps(response_data, indent=2) if response_data else "",
                "timestamp": now(),
                # "tenant_id": self.settings.tenant_id
            })
            
            log_doc.insert(ignore_permissions=True)
            
        except Exception as e:
            frappe.log_error(f"Failed to create API log: {str(e)}", "Xero API Log Error")
    
    def _log_error(self, title, message):
        """Log error message"""
        frappe.log_error(message, title)
        if self.settings.debug_mode:
            self.logger.error(f"{title}: {message}")


def get_xero_client():
    """Factory function to get Xero API client instance"""
    return XeroAPIClient()
