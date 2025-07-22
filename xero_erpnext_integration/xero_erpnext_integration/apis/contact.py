import frappe
from .base import get_xero_client
import json


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

def get_contact(self, contact_name=None):
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

@frappe.whitelist() 
def create_contact(doc, method=None):
    """Create contact in Xero"""
    try:
        client = get_xero_client()
        contact = frappe.get_doc("Contact", doc)
        contact_data = {
            "Name": contact.name,
            "FirstName": contact.first_name or "",
            "LastName": contact.last_name or "",
            "EmailAddress": contact.email_id or "",
            "AccountNumber": contact.custom_account_number or contact.name,
            "IsCustomer": True if contact.custom_is_customer == 1 else False,
            "IsSupplier": True if contact.custom_is_supplier == 1 else False,
            "Addresses": [
                {
                    "AddressType": "STREET",
                    "AddressLine1": contact.address or "",
                    # "City": contact.city,
                    # "Region": contact.state,
                    # "PostalCode": contact.postal_code,
                    # "Country": contact.country
                }
            ],
            "Phones": [
                {
                    "PhoneType": "DEFAULT",
                    "PhoneNumber": contact.phone or contact.mobile_no or ""
                }
            ]
        }
        data = {"Contacts": [contact_data]}
        response = client.make_request("POST", "/Contacts", data=data)
        
        if response:
            return {
                "status": "success",
                "data": response.get("Contacts", [])
            }
        return None
        
    except Exception as e:
        frappe.log_error(f"Failed to create contact: {str(e)}", "Xero Create Contact")
        return None