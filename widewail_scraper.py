import os
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import json

# ── Config from GitHub Secrets ──────────────────────────────────────────────
WIDEWAIL_EMAIL    = os.environ["WIDEWAIL_EMAIL"]
WIDEWAIL_PASSWORD = os.environ["WIDEWAIL_PASSWORD"]
SMTP_EMAIL        = os.environ["SMTP_EMAIL"]       # jcopenhaver@publicstorage.com
SMTP_PASSWORD     = os.environ["SMTP_PASSWORD"]    # Outlook app password


def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def login(driver):
    print("Logging into Widewail...")
    driver.get("https://app.widewail.com/login")
    wait = WebDriverWait(driver, 20)

    wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(WIDEWAIL_EMAIL)
    driver.find_element(By.NAME, "password").send_keys(WIDEWAIL_PASSWORD)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(4)
    print("Logged in.")


def navigate_to_enterprise_reviews(driver):
    print("Navigating to Enterprise Reviews...")
    wait = WebDriverWait(driver, 20)

    # Click the left nav dropdown that contains Enterprise Reviews
    try:
        # Try to find and expand the dropdown in the left sidebar
        nav_dropdown = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(),'Enterprise') or contains(@href,'enterprise')]")
        ))
        nav_dropdown.click()
        time.sleep(2)

        reviews_link = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(),'Reviews') and contains(@href,'enterprise')]")
        ))
        reviews_link.click()
        time.sleep(3)
    except Exception as e:
        print(f"Navigation attempt 1 failed: {e}")
        # Fallback: direct URL
        driver.get("https://app.widewail.com/enterprise/reviews")
        time.sleep(4)

    print(f"Current URL: {driver.current_url}")


def set_mtd_date_filter(driver):
    print("Setting date filter to Month to Date...")
    wait = WebDriverWait(driver, 20)

    try:
        # Look for a date range picker/dropdown
        date_filter = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(),'Date') or contains(text(),'date') or contains(@class,'date')]")
        ))
        date_filter.click()
        time.sleep(1)

        # Click "Month to Date" option
        mtd_option = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//li[contains(text(),'Month to Date') or contains(text(),'MTD') or contains(text(),'This Month')]")
        ))
        mtd_option.click()
        time.sleep(3)
        print("Date set to Month to Date.")
    except Exception as e:
        print(f"Date filter warning: {e} — continuing with default date range.")


def scrape_store_data(driver):
    print("Scraping store data...")
    wait = WebDriverWait(driver, 20)
    time.sleep(3)

    stores = []

    try:
        # Wait for table rows to load
        rows = wait.until(EC.presence_of_all_elements_located(
            (By.XPATH, "//table//tbody//tr")
        ))

        print(f"Found {len(rows)} rows.")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 2:
                store_name   = cols[0].text.strip()
                review_count = cols[1].text.strip()
                avg_rating   = cols[2].text.strip() if len(cols) > 2 else "N/A"

                if store_name:
                    stores.append({
                        "store":      store_name,
                        "reviews":    review_count,
                        "avg_rating": avg_rating
                    })

    except Exception as e:
        print(f"Scraping error: {e}")
        # Save screenshot for debugging
        driver.save_screenshot("/tmp/debug_screenshot.png")
        print("Screenshot saved to /tmp/debug_screenshot.png")

    print(f"Scraped {len(stores)} stores.")
    return stores


def build_email_html(stores):
    today     = datetime.now()
    month_str = today.strftime("%B")
    date_str  = today.strftime("%B %d, %Y")

    if stores:
        table_rows = ""
        for s in stores:
            rating = s['avg_rating']
            # Add star emoji based on rating
            try:
                r = float(rating)
                if r >= 4.5:
                    star = "⭐⭐⭐⭐⭐"
                elif r >= 4.0:
                    star = "⭐⭐⭐⭐"
                elif r >= 3.0:
                    star = "⭐⭐⭐"
                else:
                    star = "⭐⭐"
            except:
                star = "⭐"

            table_rows += f"""
            <tr>
                <td style="padding:10px 14px; border-bottom:1px solid #eee;">{s['store']}</td>
                <td style="padding:10px 14px; border-bottom:1px solid #eee; text-align:center;">{s['reviews']}</td>
                <td style="padding:10px 14px; border-bottom:1px solid #eee; text-align:center;">{rating} {star}</td>
            </tr>"""

        table_html = f"""
        <table style="width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px;">
            <thead>
                <tr style="background-color:#4A90D9; color:white;">
                    <th style="padding:12px 14px; text-align:left;">Store</th>
                    <th style="padding:12px 14px; text-align:center;">Reviews (MTD)</th>
                    <th style="padding:12px 14px; text-align:center;">Avg Rating</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>"""
    else:
        table_html = "<p><em>No store data could be retrieved. Please check Widewail manually.</em></p>"

    total_reviews = sum(int(s['reviews'].replace(',','')) for s in stores if s['reviews'].isdigit()) if stores else 0

    html = f"""
    <html><body style="font-family:Arial,sans-serif; color:#333; max-width:700px; margin:0 auto;">
        <p>Hey team! 👋</p>
        <p>Here's your <strong>Google Review snapshot for {month_str} month-to-date</strong> as of <strong>{date_str}</strong>:</p>

        {table_html}

        <br>
        <p>Keep up the amazing work — every review makes a difference! 🌟</p>
        <p>Feel free to reply with any questions or shoutouts.</p>
        <br>
        <p>Thanks,<br><strong>Justin</strong></p>
        <hr style="border:none; border-top:1px solid #eee; margin-top:30px;">
        <p style="font-size:11px; color:#999;">This report was automatically generated from Widewail · {date_str}</p>
    </body></html>
    """
    return html


def send_email(html_body):
    print("Sending email via Outlook SMTP...")

    today     = datetime.now()
    month_str = today.strftime("%B")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Google - MTD"
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = "jcopenhaver@publicstorage.com"

    msg.attach(MIMEText(html_body, "html"))

    # Gmail SMTP settings
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, "jcopenhaver@publicstorage.com", msg.as_string())

    print("Email sent successfully!")


def main():
    driver = get_driver()
    try:
        login(driver)
        navigate_to_enterprise_reviews(driver)
        set_mtd_date_filter(driver)
        stores = scrape_store_data(driver)
        html   = build_email_html(stores)
        send_email(html)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
