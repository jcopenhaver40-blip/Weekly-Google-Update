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
        # Use React-compatible JS to set password
        driver.execute_script("""
            var input = arguments[0];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(input, arguments[1]);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        """, password_field, WIDEWAIL_PASSWORD)
        time.sleep(1)
        print("Password set via React-compatible JS.")

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
    time.sleep(8)  # Give React extra time to render

    # Save screenshot
    driver.save_screenshot("/tmp/debug_screenshot.png")
    print("Screenshot saved.")

    stores = []

    try:
        # Check if we got redirected to login (session expired)
        if "login" in driver.current_url:
            print("ERROR: Redirected to login — session not maintained.")
            return stores

        print(f"Current URL: {driver.current_url}")
        print(f"Page title: {driver.title}")

        # Wait for ANY table or grid to appear
        wait = WebDriverWait(driver, 30)

        # Try multiple possible table/grid selectors Widewail might use
        selectors = [
            "//table//tbody//tr",
            "//div[contains(@class,'ag-row')]",          # AG Grid (common in React apps)
            "//div[contains(@class,'row') and contains(@class,'data')]",
            "//tr[contains(@class,'row')]",
            "//*[@role='row']",                           # ARIA role rows
            "//div[contains(@class,'table')]//div[contains(@class,'row')]",
        ]

        rows = []
        for selector in selectors:
            try:
                found = driver.find_elements(By.XPATH, selector)
                if found:
                    print(f"Found {len(found)} rows with selector: {selector}")
                    rows = found
                    break
            except:
                continue

        if not rows:
            print("No rows found with any selector.")
            print(f"Page source preview:\n{driver.page_source[:3000]}")
            return stores

        for row in rows:
            try:
                # Try to get all text cells in the row
                cells = row.find_elements(By.XPATH, ".//td | .//div[@role='gridcell'] | .//span[@class]")
                texts = [c.text.strip() for c in cells if c.text.strip()]
                print(f"Row texts: {texts}")

                if len(texts) >= 2:
                    stores.append({
                        "store":      texts[0],
                        "reviews":    texts[1] if len(texts) > 1 else "N/A",
                        "avg_rating": texts[2] if len(texts) > 2 else "N/A"
                    })
            except Exception as row_err:
                print(f"Row error: {row_err}")
                continue

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
