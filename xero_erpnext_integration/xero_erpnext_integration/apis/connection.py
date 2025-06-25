import frappe
from frappe import _
from .base import XeroBase

class XeroConnection(XeroBase):
    BASE_PATH = "/contacts"

    def test_connection(self, connection):
        """Test Xero API connection using configuration"""
        try:
            # Make a simple GET request to list locations
            response = self.get("", params={"key": self.api_key, "username": self.username})

            return {
                "status": "success",
                "message": "Connection test successful",
                "response": response
            }

        except Exception as e:
            error_message = str(e)

            return {
                "status": "failed",
                "message": str(e),
                "error_message": error_message
            }


@frappe.whitelist()
def test_xero_connection():
    """Helper function to test Xero connection"""
    connection = XeroConnection()
    return connection.test_connection(connection)

           