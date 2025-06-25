import frappe
from .base3 import get_xero_client

@frappe.whitelist()
def test_xero_connection():
    """Test Xero API connection"""
    try:
        client = get_xero_client()
        result = client.test_connection()
        return result
        
    except Exception as e:
        frappe.logger().error(f"Connection test failed: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist()
def get_organisation_details():
    """Get Xero organisation details"""
    try:
        client = get_xero_client()
        response = client.make_request("GET", "/Organisation")
        
        if response and response.get("Organisations"):
            return {
                "status": "success",
                "data": response["Organisations"][0]
            }
        else:
            return {
                "status": "error", 
                "message": "No organisation data found"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist()
def get_xero_contacts():
    """Get all Xero contacts"""
    try:
        client = get_xero_client()
        response = client.make_request("GET", "/Contacts")
        
        return {
            "status": "success",
            "data": response.get("Contacts", [])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist()
def get_xero_invoices():
    """Get Xero invoices"""
    try:
        client = get_xero_client()
        response = client.make_request("GET", "/Invoices")
        
        return {
            "status": "success",
            "data": response.get("Invoices", [])
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
