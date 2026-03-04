import os
import smtplib
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Fetch variables from GitHub Secrets
APN = os.environ.get("PROPERTY_APN", "").strip()
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()

def get_tax():
    # HARDCODED PATH TO PREVENT URL ERRORS
    base_url = "https://propertytax.alamedacountyca.gov"
    url = f"{base_url}?apn={APN}"
    
    with sync_playwright() as p:
        # Launch browser with a real User-Agent to avoid blocks
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to Alameda County Portal...")
            # Navigate to the correct URL
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Wait for the tax amount elements (.amount-due) to load on the page
            page.wait_for_selector(".amount-due", timeout=30000)
            
            # Scrape all instances of amount-due
            amounts = page.query_selector_all(".amount-due")
            tax_results = [amt.inner_text().strip() for amt in amounts]
            
            if not tax_results:
                return ["No amounts found. The bill might not be posted yet."]
            
            return tax_results
            
        except Exception as e:
            return [f"Error during lookup: {str(e)}", f"Target URL: {url}"]
        finally:
            browser.close()

def send_email(tax_info):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Email credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Tax Alert: {APN}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    content = f"Automated Property Tax Check for APN: {APN}\n\n"
    content += "Amounts Found:\n" + "\n".join(tax_info)
    content += f"\n\nView details here: https://propertytax.alamedacountyca.gov{APN}"
    
    msg.set_content(content)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    print("Starting Tax Lookup...")
    results = get_tax()
    print(f"Results: {results}")
    send_email(results)
