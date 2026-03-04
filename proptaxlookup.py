import os
import smtplib
import re
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Fetch variables from GitHub Secrets
APNS_RAW = os.environ.get("PROPERTY_APN", "").strip()
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()

def get_tax(apn):
    target_url = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            print(f"[{apn}] Navigating to Account Summary: {target_url}")
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            
            # Wait for JS to render
            page.wait_for_timeout(5000)
            
            # Dump the raw text of the entire page
            body_text = page.locator("body").inner_text()
            
            # Failsafe: Make sure we actually hit a tax page
            if "Total:" not in body_text and "installment" not in body_text.lower():
                return ["Could not find tax data. The APN might be invalid or the site layout changed heavily."]
            
            tax_results = []
            
            # 1. Regex to find the Total line (e.g., "Total: $12,345.67")
            total_match = re.search(r'(Total:\s*\$[0-9,]+\.\d{2})', body_text, re.IGNORECASE)
            if total_match:
                tax_results.append(total_match.group(1).strip())
                
            # 2. Regex to find the 1st installment status
            inst1 = re.search(r'(1st installment.*?\$[0-9,]+\.\d{2}.*?(?:due|paid|redeemed).*?\d{4})', body_text, re.IGNORECASE)
            if inst1:
                tax_results.append(inst1.group(1).strip())
                
            # 3. Regex to find the 2nd installment status
            inst2 = re.search(r'(2nd installment.*?\$[0-9,]+\.\d{2}.*?(?:due|paid|redeemed).*?\d{4})', body_text, re.IGNORECASE)
            if inst2:
                tax_results.append(inst2.group(1).strip())
                
            # 4. Check for Delinquent Taxes
            delinq = re.search(r'(Delinquent Taxes.*?Amount Due[^\.]*\.)', body_text, re.IGNORECASE)
            if delinq:
                tax_results.append(delinq.group(1).strip())
            
            # Return our parsed sentences, or an error if the regex found nothing
            return tax_results if tax_results else ["Page loaded, but could not extract specific tax strings."]
            
        except Exception as e:
            return [f"Error during lookup: {str(e)}"]
        finally:
            browser.close()

def requires_notification(results):
    """
    Analyzes the scraped text. 
    Ignores the "Total" line, and only flags a balance > 0 if an *installment* is due.
    """
    # 1. Always alert on errors
    for item in results:
        item_lower = item.lower()
        if "error" in item_lower or "could not find" in item_lower or "not found" in item_lower or "could not extract" in item_lower:
            return True

    amount_due = 0.0
    found_installments = False
    
    # 2. Calculate actual amount currently owed
    for item in results:
        item_lower = item.lower()
        
        # Immediate alert if delinquent taxes exist and aren't paid
        if "delinquent" in item_lower and "paid" not in item_lower and "$0.00" not in item_lower:
            return True
            
        # Only do math on the installment lines
        if "installment" in item_lower:
            found_installments = True
            
            # If the text says it's already paid or redeemed, add $0 to our due amount
            if "paid" in item_lower or "redeemed" in item_lower:
                continue
            
            # If it doesn't say paid, extract the dollar amount and add it up
            matches = re.findall(r'\$([0-9,]+\.\d{2})', item)
            if matches:
                numeric_val = float(matches[0].replace(',', ''))
                amount_due += numeric_val
                
    # 3. The Decision
    if found_installments:
        return amount_due > 0  # True if you owe money, False if it's all paid
        
    # Failsafe: if we didn't find any installments to check, alert just in case
    return True

def send_email(apn, tax_info):
    if not EMAIL_USER or not EMAIL_PASS:
        print(f"[{apn}] Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Property Tax Update: APN {apn}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    direct_link = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
    
    # Plain Text
    text_content = f"Automated Property Tax Check for APN: {apn}\n\n"
    text_content += "Results Found:\n"
    for item in tax_info:
        text_content += f"- {item}\n"
    text_content += f"\nView the official portal here: {direct_link}"
    
    msg.set_content(text_content)
    
    # HTML Content
    html_list_items = "".join(
        [f"<li style='margin-bottom: 10px; padding: 12px; background-color: #f8f9fa; border-left: 4px solid #0056b3; border-radius: 4px;'>{item}</li>" for item in tax_info]
    )
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0056b3; margin-bottom: 5px;">Alameda County Tax Alert</h2>
        <p style="font-size: 16px;">Here is the latest automated property tax check for <strong>APN: {apn}</strong>.</p>
        
        <h3 style="border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 25px;">Account Summary:</h3>
        <ul style="list-style-type: none; padding: 0; font-size: 16px;">
          {html_list_items}
        </ul>
        
        <div style="margin-top: 30px;">
            <a href="{direct_link}" style="background-color: #0056b3; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View Official Tax Portal</a>
        </div>
        
        <p style="margin-top: 40px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px;">
          This is an automated message generated by your GitHub Actions workflow.
        </p>
      </body>
    </html>
    """
    
    msg.add_alternative(html_content, subtype='html')
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print(f"[{apn}] Formatted HTML email sent successfully!")
    except Exception as e:
        print(f"[{apn}] Failed to send email: {e}")

if __name__ == "__main__":
    if not APNS_RAW:
        print("Error: PROPERTY_APN secret is empty.")
    else:
        apn_list = [apn.strip() for apn in APNS_RAW.split(",") if apn.strip()]
        print(f"Starting Tax Lookup for {len(apn_list)} APN(s)...")
        
        for current_apn in apn_list:
            print(f"\n--- Processing APN: {current_apn} ---")
            results = get_tax(current_apn)
            print(f"[{current_apn}] Scraped Data: {results}")
            
            if requires_notification(results):
                print(f"[{current_apn}] ACTION REQUIRED: Unpaid balance or error detected. Sending email...")
                send_email(current_apn, results)
            else:
                print(f"[{current_apn}] ALL CLEARED: Installments show as paid. Skipping email.")
