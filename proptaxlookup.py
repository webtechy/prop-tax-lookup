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
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        
        # Hide the webdriver flag from the firewall
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        try:
            print(f"[{apn}] Step 1: Opening the homepage front door...")
            page.goto("https://propertytax.alamedacountyca.gov/", wait_until="domcontentloaded", timeout=60000)
            
            print(f"[{apn}] Step 2: Neutralizing 'Important Notice' popups...")
            page.wait_for_timeout(3000) 
            page.keyboard.press("Escape")
            
            print(f"[{apn}] Step 3: Navigating directly to the Search portal...")
            # Bypassing the fragile button click by going straight to the organic search URL
            page.goto("https://propertytax.alamedacountyca.gov/search", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            page.keyboard.press("Escape") # Press escape again just in case the popup follows us
            
            print(f"[{apn}] Step 4: Entering APN into the search box...")
            # Find the search box by looking for placeholder text, fallback to the first text box on screen
            search_box = page.get_by_placeholder(re.compile(r"parcel|address|search", re.IGNORECASE)).first
            try:
                search_box.wait_for(state="visible", timeout=5000)
            except Exception:
                search_box = page.get_by_role("textbox").first
                search_box.wait_for(state="visible", timeout=10000)
                
            search_box.fill(apn)
            
            print(f"[{apn}] Step 5: Submitting search...")
            search_box.press("Enter")
            
            print(f"[{apn}] Step 6: Waiting for website database to populate the account summary...")
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
            
            # Buffer to let numbers fully render into the DOM
            page.wait_for_timeout(3000)
            
            raw_text = page.locator("body").inner_text()
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            if "Tracer" not in clean_text and "Tax Summary" not in clean_text:
                snippet = clean_text[:300] if clean_text.strip() else "[Blank Page]"
                return [f"ERROR: Could not load tax data. Bot saw: '{snippet}...'"]
            
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
            
            return tax_results if tax_results else ["Amount is $0.00 or fully paid."]
            
        except Exception as e:
            return [f"ERROR during interaction flow: {str(e)}"]
        finally:
            browser.close()

def send_combined_email(all_results):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Property Tax Monthly Summary"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    # 1. Build Plain Text version
    text_content = "Automated Property Tax Check Summary\n\n"
    for item in all_results:
        apn = item['apn']
        text_content += f"--- APN: {apn} ---\n"
        for res in item['results']:
            text_content += f"- {res}\n"
        text_content += f"Link: https://propertytax.alamedacountyca.gov/account-summary?apn={apn}\n\n"
        
    msg.set_content(text_content)
    
    # 2. Build HTML version
    html_content = """
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0056b3; margin-bottom: 5px;">Alameda County Tax Summary</h2>
        <p style="font-size: 16px;">Here is the monthly status report for all your tracked APNs:</p>
    """
    
    for item in all_results:
        apn = item['apn']
        direct_link = f"https://propertytax.alamedacountyca.gov/account-summary?apn={apn}"
        
        # Color the box red if it errored, blue if successful
        is_error = any("ERROR" in r for r in item['results'])
        border_color = "#dc3545" if is_error else "#0056b3"
        bg_color = "#fff3f3" if is_error else "#f8f9fa"
        
        html_list_items = "".join(
            [f"<li style='margin-bottom: 10px; padding: 12px; background-color: {bg_color}; border-left: 4px solid {border_color}; border-radius: 4px;'>{r}</li>" for r in item['results']]
        )
        
        html_content += f"""
        <h3 style="border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 25px;">APN: {apn}</h3>
        <ul style="list-style-type: none; padding: 0; font-size: 16px;">
          {html_list_items}
        </ul>
        <div style="margin-top: 15px; margin-bottom: 30px;">
            <a href="{direct_link}" style="background-color: #0056b3; color: white; padding: 10px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; font-size: 14px;">View Official Portal</a>
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
        print("Master summary email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if not APNS_RAW:
        print("Error: PROPERTY_APN secret is empty.")
    else:
        apn_list = [apn.strip() for apn in APNS_RAW.split(",") if apn.strip()]
        print(f"Starting Tax Lookup for {len(apn_list)} APN(s)...")
        
        # Gather all results regardless of amount or error
        master_results = []
        
        for current_apn in apn_list:
            print(f"\n--- Processing APN: {current_apn} ---")
            results = get_tax(current_apn)
            print(f"[{current_apn}] Scraped Data: {results}")
            master_results.append({'apn': current_apn, 'results': results})
                
        if master_results:
            print(f"\nSending a single combined email for all {len(master_results)} APN(s)...")
            send_combined_email(master_results)
