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
        
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        try:
            print(f"[{apn}] Visiting homepage first to establish session...")
            page.goto("https://propertytax.alamedacountyca.gov/", wait_until="domcontentloaded", timeout=30000)
            
            print(f"[{apn}] Waiting for popups to animate in so we can destroy them...")
            page.wait_for_timeout(3500) 
            
            page.evaluate('''() => {
                const buttons = Array.from(document.querySelectorAll('button, a'));
                buttons.forEach(btn => {
                    const t = btn.innerText.toLowerCase().trim();
                    if (t === 'ok' || t === 'close' || t === 'accept' || t === 'dismiss' || t.includes('×')) {
                        try { btn.click(); } catch(e) {}
                    }
                });
            }''')
            
            for _ in range(3):
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                
            page.evaluate('''() => {
                document.querySelectorAll('.modal-backdrop, .overlay, .cdk-overlay-backdrop, .modal').forEach(el => el.remove());
                document.body.classList.remove('modal-open');
            }''')
            
            print(f"[{apn}] Navigating directly to Account Summary...")
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
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

# THE FIX: This function now accepts a LIST of all APNs that need attention
def send_combined_email(alerts_list):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Property Tax Alert: Action Required"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    # 1. Build Plain Text version
    text_content = "Automated Property Tax Check\n\n"
    text_content += "The following APNs require your attention (unpaid balance or lookup error):\n\n"
    
    for alert in alerts_list:
        apn = alert['apn']
        text_content += f"--- APN: {apn} ---\n"
        for item in alert['results']:
            text_content += f"- {item}\n"
        text_content += f"Link: https://propertytax.alamedacountyca.gov/account-summary?apn={apn}\n\n"
        
    msg.set_content(text_content)
    
    # 2. Build HTML version
    html_content = """
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0056b3; margin-bottom: 5px;">Alameda County Tax Alert</h2>
        <p style="font-size: 16px;">The following APNs require your attention (unpaid balance or lookup error):</p>
    """
    
    for alert in alerts_list:
        apn = alert['apn']
        direct_link = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
        
        html_list_items = "".join(
            [f"<li style='margin-bottom: 10px; padding: 12px; background-color: #f8f9fa; border-left: 4px solid #0056b3; border-radius: 4px;'>{item}</li>" for item in alert['results']]
        )
        
        html_content += f"""
        <h3 style="border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 25px;">APN: {apn}</h3>
        <ul style="list-style-type: none; padding: 0; font-size: 16px;">
          {html_list_items}
        </ul>
        <div style="margin-top: 15px; margin-bottom: 30px;">
            <a href="{direct_link}" style="background-color: #0056b3; color: white; padding: 10px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; font-size: 14px;">View Official Portal for {apn}</a>
        </div>
        """
        
    html_content += """
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
        print("Combined formatted HTML email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if not APNS_RAW:
        print("Error: PROPERTY_APN secret is empty.")
    else:
        apn_list = [apn.strip() for apn in APNS_RAW.split(",") if apn.strip()]
        print(f"Starting Tax Lookup for {len(apn_list)} APN(s)...")
        
        # THE FIX: Create an empty list to gather all flags before sending emails
        alerts_to_send = []
        
        for current_apn in apn_list:
            print(f"\n--- Processing APN: {current_apn} ---")
            results = get_tax(current_apn)
            print(f"[{current_apn}] Scraped Data: {results}")
            
            if requires_notification(results):
                print(f"[{current_apn}] ACTION REQUIRED: Queuing for combined email alert...")
                # Add the data to our batch list
                alerts_to_send.append({'apn': current_apn, 'results': results})
            else:
                print(f"[{current_apn}] Amount is $0.00 or fully paid. No action needed.")
                
        # After checking all APNs, check if our list has anything in it
        if alerts_to_send:
            print(f"\nSending a single combined email for {len(alerts_to_send)} APN(s)...")
            send_combined_email(alerts_to_send)
        else:
            print("\nAll APNs checked. No alerts needed. No email sent.")
