import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url
import json
from .base import get_xero_client

class XeroSettings(Document):
    def validate(self):
        """Validate Xero Settings"""
        if self.enable:
            self.validate_required_fields()
            
    def validate_required_fields(self):
        """Validate required fields when integration is enabled"""
        required_fields = [
            ('client_id', 'Client ID'),
            ('client_secret', 'Client Secret'),
            ('redirect_uri', 'Redirect URI')
        ]
        
        for field, label in required_fields:
            if not getattr(self, field):
                frappe.throw(_("{0} is required when Xero integration is enabled").format(label))
    
    def on_update(self):
        """Clear cache when settings are updated"""
        frappe.cache().delete_key("xero_settings")
    
    def get_authorization_url(self):
        """Get OAuth authorization URL"""
        try:
            from xero_erpnext_integration.apis.base import get_xero_client
            client = get_xero_client()
            return client.get_authorization_url()
        except Exception as e:
            frappe.throw(_("Failed to generate authorization URL: {0}").format(str(e)))
    
    def exchange_auth_code(self, code, state=None):
        """Exchange authorization code for access token"""
        try:
            from xero_erpnext_integration.apis.base import get_xero_client
            client = get_xero_client()
            token = client.exchange_code_for_token(code, state)
            
            if token:
                frappe.msgprint(_("Authorization successful! Xero integration is now active."))
                return True
            else:
                frappe.throw(_("Failed to exchange authorization code"))
                
        except Exception as e:
            frappe.throw(_("Authorization failed: {0}").format(str(e)))
    
    def test_connection(self):
        """Test connection to Xero API"""
        try:
            from xero_erpnext_integration.apis.base import get_xero_client
            client = get_xero_client()
            return client.test_connection()
        except Exception as e:
            return {"status": "error", "message": str(e)}


# API Methods for Xero Settings
@frappe.whitelist()
def get_authorization_url():
    """Get OAuth authorization URL"""
    try:
        settings = frappe.get_single("Xero Settings")
        return settings.get_authorization_url()
    except Exception as e:
        frappe.throw(_("Failed to get authorization URL: {0}").format(str(e)))


@frappe.whitelist()
def handle_oauth_callback(code, state=None):
    """Handle OAuth callback"""
    try:
        settings = frappe.get_single("Xero Settings")
        return settings.exchange_auth_code(code, state)
    except Exception as e:
        frappe.throw(_("OAuth callback failed: {0}").format(str(e)))


@frappe.whitelist()
def test_xero_connection():
    """Test Xero API connection"""
    try:
        client = get_xero_client()
        return client.test_connection()
    except Exception as e:
        return {"status": "error", "message": str(e)}
