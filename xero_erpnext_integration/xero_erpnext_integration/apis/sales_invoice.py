import frappe
from .base import get_xero_client
import json


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

def get_invoice(invoice_id):
        """Get invoice from Xero"""
        try:
            client = get_xero_client()
            response = client.make_request("GET", f"Invoices/{invoice_id}")
            
            if response and "Invoices" in response:
                return {
                    "status": "success",
                    "data": response["Invoices"][0]
                }
            
            return None
            
        except Exception as e:
            frappe.log_error(f"Failed to get invoice: {str(e)}", "Xero Get Invoice")
            return None


@frappe.whitelist() 
def create_invoice(doc, method=None):
    """Create contact in Xero"""
    try:
        client = get_xero_client()
        contact = frappe.get_doc("Sales Invoice", doc)
        contact_data = {
            "FirstName": contact.first_name or "",
            "LastName": contact.last_name or "",
            "EmailAddress": contact.email_id or "",
            "AccountNumber": contact.custom_account_number,
            "Name": contact.company_name or "",
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


@frappe.whitelist()
def get_customer_contact_id(customer):
    # Method 1: Using frappe.db.sql for more control
    try:
        dynamic_links = frappe.get_all('Dynamic Link',
            filters={
                'link_doctype': 'Customer',
                'link_name': customer,
                'parenttype': 'Contact'
            },
            fields=['parent'],
            limit=1
        )
        
        if dynamic_links:
            contact_name = dynamic_links[0].parent
            contact = frappe.get_doc('Contact', contact_name)
            return contact.get('custom_contact_id')
        
        return None
    except Exception as e:
        frappe.throw("Error getting contact id for the selected customer")
