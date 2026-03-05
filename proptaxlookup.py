import os
import smtplib
import requests
from email.message import EmailMessage

# Fetch variables from GitHub Secrets
ADDRESSES_RAW = os.environ.get("PROPERTY_ADDRESSES", "").strip()
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "").strip()
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()

def get_tax_data(address):
    url = "https://api.rentcast.io/v1/properties"
    querystring = {"address": address}
    
    headers = {
        "accept": "application/json",
        "X-Api-Key": RENTCAST_API_KEY
    }
    
    try:
        # This takes milliseconds instead of 60 seconds!
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status() 
        
        data = response.json()
        
        if not data:
            return [f"ERROR: No property records found for '{address}'."]
            
        property_info = data[0]
        
        results = []
        
        # 1. Get the actual Property Tax Billed
        property_taxes = property_info.get("propertyTaxes", {})
        if property_taxes:
            # Find the most recent year in the dictionary
            latest_tax_year = max(property_taxes.keys())
            tax_amount = property_taxes[latest_tax_year].get("total", 0)
            results.append(f"Most Recent Tax Bill ({latest_tax_year}): ${tax_amount:,.2f}")
        else:
            results.append("No historical property tax bills found.")

        # 2. Get the Assessed Value (for context)
        tax_assessments = property_info.get("taxAssessments", {})
        if tax_assessments:
            latest_assessed_year = max(tax_assessments.keys())
            assessed_value = tax_assessments[latest_assessed_year].get("value", 0)
            results.append(f"County Assessed Value ({latest_assessed_year}): ${assessed_value:,.2f}")
            
        return results

    except requests.exceptions.RequestException as e:
        return [f"API Connection Error: {str(e)}"]

def send_combined_email(all_results):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Property Tax API Summary"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    # 1. Plain Text version
    text_content = "Automated Property Tax Check Summary\n\n"
    for item in all_results:
        addr = item['address']
        text_content += f"--- Property: {addr} ---\n"
        for res in item['results']:
            text_content += f"- {res}\n"
        text_content += "\n"
        
    msg.set_content(text_content)
    
    # 2. HTML version
    html_content = """
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0056b3; margin-bottom: 5px;">Property Tax Data Summary</h2>
        <p style="font-size: 16px;">Here is the latest backend data pulled directly from the RentCast API:</p>
    """
    
    for item in all_results:
        addr = item['address']
        
        # Color formatting
        is_error = any("ERROR" in r for r in item['results'])
        border_color = "#dc3545" if is_error else "#28a745"
        bg_color = "#fff3f3" if is_error else "#f8fff9"
        
        html_list_items = "".join(
            [f"<li style='margin-bottom: 10px; padding: 12px; background-color: {bg_color}; border-left: 4px solid {border_color}; border-radius: 4px;'>{r}</li>" for r in item['results']]
        )
        
        html_content += f"""
        <h3 style="border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 25px;">📍 {addr}</h3>
        <ul style="list-style-type: none; padding: 0; font-size: 16px;">
          {html_list_items}
        </ul>
        """
        
    html_content += """
        <p style="margin-top: 40px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px;">
          This is an automated message generated via the RentCast API.
        </p>
      </body>
    </html>
    """
    
    msg.add_alternative(html_content, subtype='html')
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("API summary email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if not RENTCAST_API_KEY:
        print("Error: RENTCAST_API_KEY secret is missing.")
    elif not ADDRESSES_RAW:
        print("Error: PROPERTY_ADDRESSES secret is empty.")
    else:
        # Split the addresses by comma
        address_list = [addr.strip() for addr in ADDRESSES_RAW.split("|") if addr.strip()]
        print(f"Starting API Lookup for {len(address_list)} propert(ies)...")
        
        master_results = []
        
        for current_address in address_list:
            print(f"\n--- Querying API for: {current_address} ---")
            results = get_tax_data(current_address)
            print(f"[{current_address}] API Response: {results}")
            master_results.append({'address': current_address, 'results': results})
                
        if master_results:
            send_combined_email(master_results)
