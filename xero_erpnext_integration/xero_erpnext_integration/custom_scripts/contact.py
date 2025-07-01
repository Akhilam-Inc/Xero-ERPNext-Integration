import frappe
from frappe import _

def on_update(doc, method):
    """
    Trigger Xero contact creation when custom_send_to_xero is checked
    and the contact wasn't previously sent to Xero
    """
    # Check if custom_send_to_xero is checked and contact_id is not set
    # This ensures we only create contact once when checkbox is first checked
    if (doc.get('custom_send_to_xero') and 
        not doc.get('custom_contact_id') and 
        doc.get('custom_account_number')):
        
        try:
            # Call the Xero API to create contact
            from xero_erpnext_integration.xero_erpnext_integration.apis.contact import create_contact
            
            result = create_contact(doc.name)
            
            if result and result.get('status') == 'success':
                # Update the document with Xero contact ID
                frappe.db.set_value('Contact', doc.name, 'custom_contact_id', result['data'][0]['ContactID'])
                frappe.db.set_value('Contact', doc.name, 'custom_send_to_xero', 1)  # Ensure it stays checked
                
                # Reload the document to reflect the changes
                doc.reload()
                
                frappe.msgprint(
                    _("Contact created successfully in Xero"),
                    title=_("Success"),
                    indicator="green"
                )
            else:
                # Reset the checkbox if creation failed
                frappe.db.set_value('Contact', doc.name, 'custom_send_to_xero', 0)
                doc.reload()
                frappe.throw(_("Error creating contact in Xero"))
                
        except Exception as e:
            # Reset the checkbox if there's an error
            frappe.db.set_value('Contact', doc.name, 'custom_send_to_xero', 0)
            doc.reload()
            frappe.log_error(f"Xero Contact Creation Error: {str(e)}")
            frappe.throw(_("Error creating contact in Xero: {0}").format(str(e)))
    
    elif doc.get('custom_send_to_xero') and not doc.get('custom_account_number'):
        # Reset checkbox if account number is missing
        frappe.db.set_value('Contact', doc.name, 'custom_send_to_xero', 0)
        doc.reload()
        frappe.throw(_("Please enter account number to create contact in Xero"))
