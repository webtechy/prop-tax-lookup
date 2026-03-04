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
    apn = apn.strip()
    target_url = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        page = context.new_page()
        
        try:
            print(f"[{apn}] Visiting homepage first to establish session...")
            page.goto("https://propertytax.alamedacountyca.gov/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000) 
            
            print(f"[{apn}] Navigating directly to Account Summary: {target_url}")
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            
            print(f"[{apn}] Waiting for website database to populate the real numbers...")
            try:
                page.wait_for_function(
                    '''() => {
                        const text = document.body.innerText.toLowerCase();
                        const hasInstallment = text.includes("installment");
                        const hasRealTotal = text.includes("total:") && !text.includes("total: $0.00");
                        const hasError = text.includes("no results") || text.includes("not found");
                        
                        return hasInstallment || hasRealTotal || hasError;
                    }''',
                    timeout=30000
                )
            except Exception:
                print(f"[{apn}] Warning: Wait timed out. The site might be extremely slow.")
            
            page.wait_for_timeout(2000)
            
            raw_text = page.locator("body").inner_text()
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            if "Total:" not in clean_text and "installment" not in clean_text.lower():
                snippet = clean_text[:250] if clean_text.strip() else "[Blank Page]"
                return [f"ERROR: Could not load tax data. What the bot saw: '{snippet}...'"]
            
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
    # 1. Always send email if an error is detected
    for item in results:
        item_lower = item.lower()
        if "error" in item_lower or "could not load" in item_lower or "what the bot saw" in item_lower:
            return True

    unpaid_balance_found = False
    dollar_signs_seen = False
    
    # 2. Extract and check every single dollar amount found
    for item in results:
        item_lower = item.lower()
        matches = re.findall(r'\$([0-9,]+\.\d{2})', item)
        
        if matches:
            dollar_signs_seen = True
            
        # If the sentence explicitly says paid/redeemed, ignore its dollar amount ($0 owed)
        if "paid" in item_lower or "redeemed" in item_lower:
            continue
            
        # Check the parsed amounts in this line
        for match in matches:
            val = float(match.replace(',', ''))
            
            if val > 0.0:
                # If we hit a number > 0, we need to make sure it's not JUST the "Total: $9000" 
                # line while the installments below it are fully paid.
                if "total" in item_lower and len(results) > 1:
                    pass # Ignore the Total line if we have specific installment details below it
                else:
                    unpaid_balance_found = True

    # 3. Final Decision
    if dollar_signs_seen:
        # If we saw dollar signs, but unpaid_balance_found is False, it means everything was $0.00 or Paid!
        return unpaid_balance_found
        
    # Failsafe: if we literally found no dollar amounts, send an email to warn us something is weird
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
    
    text_content = f"Automated Property Tax Check for APN: {apn}\n\n"
    text_content += "Account Summary:\n"
    for item in tax_info:
        text_content += f"- {item}\n"
    text_content += f"\nView the official portal here: {direct_link}"
    
    msg.set_content(text_content)
    
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
                # Explicitly logging that the amount was $0 and blocking the email
                print(f"[{current_apn}] Amount is $0.00 or fully paid. Email not sent.")
