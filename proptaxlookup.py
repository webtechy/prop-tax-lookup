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
    # Clean up the APN in case there are stray spaces in the GitHub Secret
    apn = apn.strip()
    target_url = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            print(f"[{apn}] Navigating directly to Account Summary: {target_url}")
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            
            # THE FIX: Force the scraper to wait for the actual data to hydrate!
            # The county site will only show the word "Tracer" once the real data loads.
            print(f"[{apn}] Waiting for website database to populate the numbers...")
            try:
                page.wait_for_function(
                    '() => document.body.innerText.includes("Tracer") || document.body.innerText.includes("Tax History")',
                    timeout=20000
                )
            except Exception:
                print(f"[{apn}] Warning: Data took too long to load or the APN is invalid.")
            
            # Small 2-second buffer to let the HTML finish rendering
            page.wait_for_timeout(2000)
            
            raw_text = page.locator("body").inner_text()
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            # If it still doesn't see "Tracer", it means we are stuck on the dummy $0.00 template
            if "Tracer" not in clean_text and "Tax History" not in clean_text:
                return [f"Could not load tax data. The APN '{apn}' might be formatted incorrectly or the site is down."]
            
            tax_results = []
            
            total_match = re.search(r'(Total:\s*\$[0-9,]+\.\d{2})', clean_text, re.IGNORECASE)
            if total_match:
                tax_results.append(total_match.group(1).strip())
                
            inst1 = re.search(r'((?:Your|The)?\s*1st installment.*?\$[0-9,]+\.\d{2}.*?(?:\d{4}))', clean_text, re.IGNORECASE)
            if inst1:
                tax_results.append(inst1.group(1).strip() + ".")
                
            inst2 = re.search(r'((?:Your|The)?\s*2nd installment.*?\$[0-9,]+\.\d{2}.*?(?:\d{4}))', clean_text, re.IGNORECASE)
            if inst2:
                tax_results.append(inst2.group(1).strip() + ".")
                
            delinq = re.search(r'(Delinquent Taxes.*?Amount Due[^\.]*\.)', clean_text, re.IGNORECASE)
            if delinq:
                tax_results.append(delinq.group(1).strip())
            
            return tax_results if tax_results else ["Page loaded, but could not extract specific tax strings."]
            
        except Exception as e:
            return [f"Error during lookup: {str(e)}"]
        finally:
            browser.close()

def requires_notification(results):
    for item in results:
        item_lower = item.lower()
        if "error" in item_lower or "could not load" in item_lower or "could not extract" in item_lower:
            return True

    amount_due = 0.0
    found_installments = False
    
    for item in results:
        item_lower = item.lower()
        
        if "delinquent" in item_lower and "paid" not in item_lower and "$0.00" not in item_lower:
            return True
            
        if "installment" in item_lower:
            found_installments = True
            
            if "paid" in item_lower or "redeemed" in item_lower:
                continue
            
            matches = re.findall(r'\$([0-9,]+\.\d{2})', item)
            if matches:
                numeric_val = float(matches[0].replace(',', ''))
                amount_due += numeric_val
                
    if found_installments:
        return amount_due > 0 
        
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
    
    # Plain Text Fallback
    text_content = f"Automated Property Tax Check for APN: {apn}\n\n"
    text_content += "Account Summary:\n"
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
