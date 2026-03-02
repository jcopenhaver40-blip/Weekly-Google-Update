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
    driver.get("https://apps.widewail.com/login")
    wait = WebDriverWait(driver, 20)
    time.sleep(4)

    try:
        # Step 1: Find email field and type using JavaScript
        print("Step 1: Entering email...")
        email_field = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input")
        ))

        # Use JavaScript to set value AND trigger React's synthetic events
        driver.execute_script("""
            var input = arguments[0];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(input, arguments[1]);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        """, email_field, WIDEWAIL_EMAIL)
        time.sleep(2)
        print(f"Email set via React-compatible JS: {WIDEWAIL_EMAIL}")

        driver.save_screenshot("/tmp/debug_screenshot.png")
        print("Email entered — screenshot saved.")

        # Press Enter to continue instead of clicking button
        from selenium.webdriver.common.keys import Keys
        email_field.send_keys(Keys.RETURN)
        print("Pressed Enter after email.")
        time.sleep(4)

        driver.save_screenshot("/tmp/debug_screenshot.png")
        print(f"After continue URL: {driver.current_url}")

        # Step 2: Enter password
        print("Step 2: Entering password...")
        password_field = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input[@type='password']")
        ))
        driver.execute_script("arguments[0].click(); arguments[0].focus();", password_field)
        time.sleep(0.5)

        actions2 = ActionChains(driver)
        actions2.click(password_field)
        actions2.send_keys(WIDEWAIL_PASSWORD)
        actions2.perform()
        time.sleep(1)

        # Click submit
        submit_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button")
        ))
        driver.execute_script("arguments[0].click();", submit_btn)
        print("Clicked submit.")
        time.sleep(6)

        driver.save_screenshot("/tmp/debug_screenshot.png")
        print(f"After login URL: {driver.current_url}")

    except Exception as e:
        print(f"Login error: {e}")
        driver.save_screenshot("/tmp/debug_screenshot.png")
        raise


def navigate_to_enterprise_reviews(driver):
    print("Navigating to Enterprise Reviews with MTD date range...")

    today = datetime.now()
    # First day of current month
    start_date = today.replace(day=1).strftime("%Y-%m-%dT00:00:00.000-08:00")
    # Today as end date
    end_date = today.strftime("%Y-%m-%dT23:59:59.999-08:00")

    from urllib.parse import quote
    start_encoded = quote(start_date, safe="")
    end_encoded   = quote(end_date, safe="")

    url = (
        f"https://apps.widewail.com/report/enterprise"
        f"?dateRange%5BstartDate%5D={start_encoded}"
        f"&dateRange%5BendDate%5D={end_encoded}"
        f"&sort=rowLabel%2Casc"
        f"&report=OVERVIEW"
        f"&compareMode=RELATIVE"
        f"&c-OVERVIEW%5Blabel%5D=Location"
        f"&c-OVERVIEW%5Blabel%5D=Total%20Reviews"
        f"&c-OVERVIEW%5Blabel%5D=Rating"
        f"&c-OVERVIEW%5Bhidden%5D=false"
        f"&c-OVERVIEW%5Bhidden%5D=false"
        f"&c-OVERVIEW%5Bhidden%5D=false"
    )

    driver.get(url)
    time.sleep(5)
    print(f"Navigated to: {driver.current_url}")


def set_mtd_date_filter(driver):
    # Date is already set via URL — nothing to do here
    print("Date range set via URL — skipping manual filter step.")


def scrape_store_data(driver):
    print("Waiting for data to load...")
    wait = WebDriverWait(driver, 30)
    time.sleep(6)  # Give the page extra time to render

    stores = []

    try:
        # Save screenshot for debugging
        driver.save_screenshot("/tmp/debug_screenshot.png")
        print("Screenshot saved.")

        # Try to find table rows
        rows = driver.find_elements(By.XPATH, "//table//tbody//tr")
        print(f"Found {len(rows)} rows.")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 2:
                store_name   = cols[0].text.strip()
                review_count = cols[1].text.strip() if len(cols) > 1 else "N/A"
                avg_rating   = cols[2].text.strip() if len(cols) > 2 else "N/A"

                if store_name and store_name != "":
                    stores.append({
                        "store":      store_name,
                        "reviews":    review_count,
                        "avg_rating": avg_rating
                    })

        if not stores:
            # Try alternative: look for any grid/list structure
            print("No table rows found — trying alternative selectors...")
            print(f"Page source preview: {driver.page_source[:2000]}")

    except Exception as e:
        print(f"Scraping error: {e}")
        driver.save_screenshot("/tmp/debug_screenshot.png")

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
