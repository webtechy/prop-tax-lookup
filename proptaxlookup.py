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
    safe_apn_name = apn.replace(" ", "_").replace("-", "_")
    screenshot_path = f"debug_{safe_apn_name}.png"
    
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
            page.goto("https://propertytax.alamedacountyca.gov/search", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            page.keyboard.press("Escape") 
            
            print(f"[{apn}] Step 4: Entering APN into the search box...")
            search_box = page.get_by_placeholder(re.compile(r"parcel|address|search", re.IGNORECASE)).first
            try:
                search_box.wait_for(state="visible", timeout=5000)
            except Exception:
                # If the placeholder fails, just grab the very first text box on the page
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
                print(f"[{apn}] Warning: Wait timed out. Taking error screenshot...")
            
            # Buffer to let any final layout shifts settle
            page.wait_for_timeout(3000)
            
            # THE FIX: Take a picture of exactly what the bot sees at the end of the run
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"[{apn}] Screenshot captured and saved to {screenshot_path}")
            
            raw_text = page.locator("body").inner_text()
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            if "Tracer" not in clean_text and "Tax Summary" not in clean_text:
                snippet = clean_text[:300] if clean_text.strip() else "[Blank Page]"
                return {"results": [f"ERROR: Could not load tax data. See attached screenshot. Bot text saw: '{snippet}...'"], "screenshot": screenshot_path}
            
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
            
            if not tax_results:
                tax_results = ["Amount is $0.00 or fully paid."]
                
            return {"results": tax_results, "screenshot": screenshot
