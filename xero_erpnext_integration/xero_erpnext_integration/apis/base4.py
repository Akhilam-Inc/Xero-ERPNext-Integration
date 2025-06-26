import frappe
import requests
import base64
import json
from datetime import datetime
from frappe.utils import now_datetime, add_to_date, get_datetime

class XeroBaseClient:
    """Base client for Xero API requests with token and tenant management"""

    def __init__(self):
        self.base_url = "https://api.xero.com/api.xro/2.0"
        self.token_url = "https://identity.xero.com/connect/token"
        self.connections_url = "https://api.xero.com/connections"
        self.settings = self._get_settings()
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self.tenant_id = None

    def _get_settings(self):
        try:
            return frappe.get_single("Xero Settings")
        except:
            frappe.throw("Xero Settings not found. Please configure Xero integration.")

    def _get_settings_from_db(self):
        return frappe.db.get_value("Xero Settings", "Xero Settings", 
            ["client_id", "client_secret", "access_token", "refresh_token", "token_expires_at", "tenant_id", "redirect_uri", "debug_mode"],
            as_dict=True)

    def _update_settings(self, updates):
        try:
            for field, value in updates.items():
                frappe.db.set_value("Xero Settings", None, field, value, update_modified=False)
            frappe.db.commit()
            frappe.clear_cache(doctype="Xero Settings")
            return True
        except Exception as e:
            frappe.log_error(f"Xero DB Update Failed: {str(e)}")
            frappe.db.rollback()
            return False

    def _get_basic_auth_header(self):
        settings = self._get_settings_from_db()
        credentials = f"{settings['client_id']}:{settings['client_secret']}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def generate_authorization_url(self):
        settings = self._get_settings()
        scope = "offline_access accounting.transactions accounting.settings"
        return (
            f"https://login.xero.com/identity/connect/authorize?"
            f"response_type=code&client_id={settings.client_id}&redirect_uri={settings.redirect_uri}"
            f"&scope={scope}&state=random_state_value"
        )

    def exchange_code_for_token(self, code):
        settings = self._get_settings_from_db()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.get("redirect_uri")
        }
        headers = {
            "Authorization": self._get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(self.token_url, headers=headers, data=data)

        self._log_api_call("/connect/token", "POST", data, response.text, response.status_code)

        if response.status_code == 200:
            tokens = response.json()
            self.access_token = tokens["access_token"]
            self.refresh_token = tokens["refresh_token"]
            self.token_expires_at = add_to_date(now_datetime(), seconds=tokens["expires_in"] - 300)
            self._update_settings({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expires_at": self.token_expires_at
            })
            self._get_tenant_id(self.access_token)
        else:
            frappe.throw(f"Failed to exchange code: {response.text}")

    def refresh_access_token(self):
        settings = self._get_settings_from_db()
        data = {
            "grant_type": "refresh_token",
            "refresh_token": settings.get("refresh_token")
        }
        headers = {
            "Authorization": self._get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(self.token_url, headers=headers, data=data)

        self._log_api_call("/connect/token", "POST", data, response.text, response.status_code)

        if response.status_code == 200:
            tokens = response.json()
            self.access_token = tokens["access_token"]
            self.refresh_token = tokens["refresh_token"]
            self.token_expires_at = add_to_date(now_datetime(), seconds=tokens["expires_in"] - 300)
            self._update_settings({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expires_at": self.token_expires_at
            })
        else:
            if "invalid_grant" in response.text:
                frappe.throw("Refresh token expired or invalid. Please reconnect to Xero.")
            frappe.throw(f"Failed to refresh token: {response.text}")

    def _get_tenant_id(self, access_token):
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        response = requests.get(self.connections_url, headers=headers)

        self._log_api_call("/connections", "GET", None, response.text, response.status_code)

        if response.status_code == 200:
            connections = response.json()
            if connections:
                self.tenant_id = connections[0].get("tenantId")
                self._update_settings({"tenant_id": self.tenant_id})
        else:
            frappe.throw(f"Failed to get tenant ID: {response.text}")

    def _is_token_expired(self):
        settings = self._get_settings_from_db()
        if not settings.get("token_expires_at"):
            return True
        expires_at = get_datetime(settings["token_expires_at"])
        return now_datetime() >= expires_at

    def _ensure_token(self):
        settings = self._get_settings_from_db()
        self.access_token = settings.get("access_token")
        self.refresh_token = settings.get("refresh_token")
        self.token_expires_at = settings.get("token_expires_at")
        self.tenant_id = settings.get("tenant_id")

        if self._is_token_expired():
            self.refresh_access_token()

    def make_request(self, method, endpoint, data=None, params=None):
        self._ensure_token()
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Xero-tenant-id": self.tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        try:
            if method == "GET":
                res = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                res = requests.post(url, headers=headers, json=data)
            elif method == "PUT":
                res = requests.put(url, headers=headers, json=data)
            elif method == "DELETE":
                res = requests.delete(url, headers=headers)
            else:
                frappe.throw("Unsupported method")

            self._log_api_call(endpoint, method, data or params, res.text, res.status_code)

            if res.status_code in [200, 201]:
                return res.json()
            else:
                frappe.throw(f"API Request Failed: {res.status_code} - {res.text}")
        except Exception as e:
            self._log_api_call(endpoint, method, data, str(e), 500)
            frappe.throw(f"Request error: {str(e)}")

    def _log_api_call(self, endpoint, method, request_payload=None, response_body=None, status_code=None, error_message=None):
        try:
            frappe.get_doc({
                "doctype": "Xero API Log",
                "api_url": endpoint,
                "api_method": method,
                "payload": json.dumps(request_payload) if request_payload else None,
                "response": response_body if isinstance(response_body, str) else json.dumps(response_body),
                "status_code": status_code,
                "message": error_message,
                "timestamp": now_datetime()
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error("Xero Log Error", str(e))

# Singleton instance
_xero_client = None

def get_xero_client():
    global _xero_client
    if _xero_client is None:
        _xero_client = XeroBaseClient()
    return _xero_client
