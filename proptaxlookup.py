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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        
        # THE FIX: Hide the fact that we are a bot from the county's firewall
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        try:
            print(f"[{apn}] Visiting homepage first to establish session...")
            page.goto("https://propertytax.alamedacountyca.gov/", wait_until="domcontentloaded", timeout=30000)
            
            # THE FIX: Press 'Escape' to dismiss the "Important Notice 2025-26" modal!
            page.keyboard.press("Escape")
            page.wait_for_timeout(2000) 
            
            print(f"[{apn}] Navigating directly to Account Summary...")
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            # Press escape again just in case the modal follows us to the new page
            page.keyboard.press("Escape")
            
            print(f"[{apn}] Waiting for website database to populate the real numbers...")
            try:
                page.wait_for_function(
                    '''() => {
                        const text = document.body.innerText.toLowerCase();
                        return text.includes("tracer") || text.includes("tax summary") || text.includes("no results");
                    }''',
                    timeout=25000
                )
            except Exception:
                print(f"[{apn}] Warning: Wait timed out. Proceeding to scrape anyway...")
            
            page.wait_for_timeout(3000)
            
            raw_text = page.locator("body").inner_text()
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            if "Tracer" not in clean_text and "Tax Summary" not in clean_text:
                snippet = clean_text[:300] if clean_text.strip() else "[Blank Page]"
                return [f"ERROR: Could not load actual tax data. The firewall or a popup is blocking the bot. What the bot saw: '{snippet}...'"]
            
            tax_results = []
            
            tracer_match = re.search(r'(\d{4}-\d{4}\s*Secured\s*Tracer #\s*\d+|Tracer #\s*\d+)', clean_text, re.IGNORECASE)
            if tracer_match:
                tax_results.append(tracer_match.group(1).strip())
            
            # Use negative lookbehind to ensure we NEVER grab the "Sub Total" from the header Cart
            totals = re.findall(r'(?<!Sub\s)(Total:\s*\$[0-9,]+\.\d{2})', clean_text, re.IGNORECASE)
            if totals:
                real_totals = [t for t in totals if "$0.00" not in t]
                tax_results.append(real_totals[-1].strip() if real_totals else totals[-1].strip())
                
            inst1s = re.findall(r'((?:Your|The)?\s*1st installment.*?\$[0-9,]+\.\d{2}.*?(?:\d{4}))', clean_text, re.IGNORECASE)
            if inst1s:
                tax_results.append(inst1s[-1].strip() + ".")
                
            inst2s = re.findall(r'((?:Your|The)?\s*2nd installment.*?\$[0-9,]+\.\d{2}.*?(?:\d{4}))', clean_text, re.IGNORECASE)
            if inst2s:
                tax_results.append(inst2s[-1].strip() + ".")
                
            delinqs = re.findall(r'(Delinquent Taxes.*?Amount Due[^\.]*\.)', clean_text, re.IGNORECASE)
            if delinqs:
                tax_results.append(delinqs[-1].strip())
            
            return tax_results if tax_results else ["Page loaded, but could not extract specific tax strings."]
            
        except Exception as e:
            return [f"Error during lookup: {str(e)}"]
        finally:
            browser.close()

def requires_notification(results):
    for item in results:
        item_lower = item.lower()
        if "error" in item_lower or "could not load" in item_lower or "what the bot saw" in item_lower:
            return True

    unpaid_balance_found = False
    dollar_signs_seen = False
    
    for item in results:
        item_lower = item.lower()
        matches = re.findall(r'\$([0-9,]+\.\d{2})', item)
        
        if matches:
            dollar_signs_seen = True
            
        if "paid" in item_lower or "redeemed" in item_lower:
            continue
            
        for match in matches:
            val = float(match.replace(',', ''))
            
            if val > 0.0:
                if "total" in item_lower and len(results) > 2:
                    pass 
                else:
                    unpaid_balance_found = True

    if dollar_signs_seen:
        return unpaid_balance_found
        
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
                print(f"[{current_apn}] Amount is $0.00 or fully paid. Email not sent.")
