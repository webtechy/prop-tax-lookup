import os
import smtplib
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Config from GitHub Secrets
APN = os.environ["PROPERTY_APN"]
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"] # Use a Google "App Password"

def get_tax():
    url = f"https://propertytax.alamedacountyca.gov{APN}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector(".amount-due", timeout=15000)
        amounts = [amt.inner_text() for amt in page.query_selector_all(".amount-due")]
        browser.close()
        return amounts

def send_email(body):
    msg = EmailMessage()
    msg.set_content(f"Alameda County Tax Update for {APN}:\n\n" + "\n".join(body))
    msg['Subject'] = "Property Tax Lookup Result"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER # Sends to yourself
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)

if __name__ == "__main__":
    data = get_tax()
    send_email(data)
