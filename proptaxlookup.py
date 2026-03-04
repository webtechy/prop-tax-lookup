import os
import smtplib
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

APN = os.environ.get("PROPERTY_APN", "").strip()
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()

def get_tax():
    base_url = "https://propertytax.alamedacountyca.gov"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Setting a standard window size helps the site layout properly
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        
        try:
            print(f"Navigating to {base_url}...")
            page.goto(base_url, wait_until="networkidle", timeout=60000)
            
            # 1. Locate the APN input field and fill it
            print(f"Entering APN: {APN}")
            page.wait_for_selector('input[name="apn"]', timeout=20000)
            page.fill('input[name="apn"]', APN)
            
            # 2. Click the 'Search' button
            print("Clicking Search...")
            page.click('button[type="submit"]')
            
            # 3. Wait for the results to load (looking for the tax amount class)
            print("Waiting for results...")
            page.wait_for_selector(".amount-due", timeout=30000)
            
            # 4. Extract all tax amounts found
            amounts = page.query_selector_all(".amount-due")
            tax_results = [amt.inner_text().strip() for amt in amounts if amt.inner_text().strip()]
            
            return tax_results if tax_results else ["No amounts listed on the page."]
            
        except Exception as e:
            return [f"Error: {str(e)}"]
        finally:
            browser.close()

def send_email(tax_info):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Tax Alert: {APN}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    body = f"Automated Check for APN: {APN}\n\n"
    body += "Results Found:\n" + "\n".join(tax_info)
    body += f"\n\nLink: https://propertytax.alamedacountyca.gov"
    
    msg.set_content(body)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("Email sent!")
    except Exception as e:
        print(f"Email failed: {e}")

if __name__ == "__main__":
    if not APN:
        print("Error: PROPERTY_APN secret is empty.")
    else:
        results = get_tax()
        print(f"Final Results: {results}")
        send_email(results)
