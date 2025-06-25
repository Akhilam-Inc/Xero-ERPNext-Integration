import frappe
from frappe import _
from .base2 import XeroAPIClient

@frappe.whitelist()
def test_connection():
    """
    Test the connection to Xero API.
    Returns a success message if the connection is successful.
    """
    try:
        client = XeroAPIClient()
        client.test_connection()  # Attempt to fetch contacts to verify connection
        return {"message": _("Connection to Xero API is successful.")}
    except Exception as e:
        frappe.log_error(f"Xero API Connection Error: {str(e)}", "Xero Connection Error")
        return {"error": _("Failed to connect to Xero API. Please check your settings and try again.")}