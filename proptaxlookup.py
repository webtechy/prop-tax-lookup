import os
import smtplib
import re
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Fetch variables from GitHub Secrets
APN = os.environ.get("PROPERTY_APN", "").strip()
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()

def get_tax():
    target_url = f"https://propertytax.alamedacountyca.gov/account-summary?apn={APN}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            print(f"Navigating directly to Account Summary: {target_url}")
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            
            page.wait_for_timeout(5000)
            
            body_text = page.locator("body").inner_text()
            if "Total:" not in body_text and "Tracer" not in body_text and "$" not in body_text:
                return ["Could not find tax data. The APN might be invalid or the site layout changed."]
            
            amounts = page.query_selector_all(".amount-due")
            tax_results = [amt.inner_text().strip() for amt in amounts if amt.inner_text().strip()]
            
            if not tax_results:
                print("Specific amount classes not found, parsing text directly...")
                elements = page.query_selector_all("p, span, div")
                for el in elements:
                    text = el.inner_text().strip()
                    if ("$" in text) and ("Total:" in text or "installment" in text.lower()) and ("\n" not in text):
                        if text not in tax_results:
                            tax_results.append(text)
            
            return tax_results if tax_results else ["Page loaded, but specific amount elements were not found."]
            
        except Exception as e:
            return [f"Error during lookup: {str(e)}"]
        finally:
            browser.close()

def requires_notification(results):
    """
    Analyzes the scraped results. Returns True if there is a balance > 0 or an error.
    Returns False if all dollar amounts found are exactly $0.00.
    """
    for item in results:
        item_lower = item.lower()
        if "error" in item_lower or "could not find" in item_lower or "not found" in item_lower:
            return True

    has_balance = False
    amounts_found = 0
    
    for item in results:
        matches = re.findall(r'\$([0-9,]+\.\d{2})', item)
        for match in matches:
            amounts_found += 1
            numeric_val = float(match.replace(',', ''))
            if numeric_val > 0.0:
                has_balance = True
                
    if has_balance:
        return True
        
    if amounts_found > 0 and not has_balance:
        return False
        
    return True

def send_email(tax_info):
    if not EMAIL_USER or not EMAIL_PASS:
        print("Credentials missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Alameda Property Tax Update: APN {APN}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    
    direct_link = f"https://propertytax.alamedacountyca.gov/account-summary?apn={APN}"
    
    # Plain Text
    text_content = f"Automated Property Tax Check for APN: {APN}\n\n"
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
        <p style="font-size: 16px;">Here is the latest automated property tax check for <strong>APN: {APN}</strong>.</p>
        
        <h3 style="border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 25px;">Amounts Due:</h3>
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
        print("Formatted HTML email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if not APN:
        print("Error: PROPERTY_APN secret is empty.")
    else:
        print("Starting Tax Lookup...")
        results = get_tax()
        print(f"Final Results: {results}")
        
        if requires_notification(results):
            print("Actionable balance or error detected. Sending email alert...")
            send_email(results)
        else:
            print("All balances are $0.00. Skipping email to keep your inbox clean!")
