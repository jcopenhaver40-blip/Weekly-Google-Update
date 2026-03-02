import os
import json
import boto3
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ── Config from GitHub Secrets ───────────────────────────────────────────────
WIDEWAIL_EMAIL    = os.environ["WIDEWAIL_EMAIL"]
WIDEWAIL_PASSWORD = os.environ["WIDEWAIL_PASSWORD"]
SMTP_EMAIL        = os.environ["SMTP_EMAIL"]
SMTP_PASSWORD     = os.environ["SMTP_PASSWORD"]

# Widewail's AWS Cognito config
COGNITO_CLIENT_ID = "3grsbeh874ie3uurt2p1r5s3kp"
COGNITO_REGION    = "us-east-1"


def get_auth_token():
    print("Authenticating with Cognito...")
    client = boto3.client("cognito-idp", region_name=COGNITO_REGION)
    response = client.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": WIDEWAIL_EMAIL,
            "PASSWORD": WIDEWAIL_PASSWORD,
        },
        ClientId=COGNITO_CLIENT_ID,
    )
    token = response["AuthenticationResult"]["IdToken"]
    print("Authentication successful!")
    return token


def get_enterprise_reviews(token):
    print("Fetching enterprise review data...")
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    today      = datetime.now()
    start_date = today.replace(day=1).strftime("%Y-%m-%dT00:00:00.000-08:00")
    end_date   = today.strftime("%Y-%m-%dT23:59:59.999-08:00")

    all_stores = []
    page = 0

    while True:
        params = {
            "sort":        "rowLabel,asc",
            "compareMode": "RELATIVE",
            "startDate":   start_date,
            "endDate":     end_date,
            "page":        page,
            "size":        25,
            "frequency":   "DAILY",
            "mode":        "OVERVIEW",
        }

        print(f"Fetching page {page}...")
        r = requests.get(
            "https://api.widewail.com/v1/report/group",
            headers=headers,
            params=params,
            timeout=30
        )
        print(f"Status: {r.status_code}")

        if r.status_code != 200:
            print(f"Error response: {r.text[:500]}")
            break

        data = r.json()
        print(f"Response preview: {json.dumps(data, indent=2)[:1000]}")

        # Extract rows from response
        rows = None
        if isinstance(data, list):
            rows = data
        elif "content" in data:
            rows = data["content"]
        elif "data" in data:
            rows = data["data"]
        elif "rows" in data:
            rows = data["rows"]

        if not rows:
            print("No rows found in response.")
            break

        all_stores.extend(rows)

        # Check if there are more pages
        if isinstance(data, dict):
            total_pages = data.get("totalPages", 1)
            if page + 1 >= total_pages:
                break
        else:
            break

        page += 1

    print(f"Total stores fetched: {len(all_stores)}")
    return all_stores


def parse_stores(rows):
    stores = []
    if not rows:
        return stores

    for row in rows:
        if isinstance(row, dict):
            print(f"Row keys: {list(row.keys())}")
            # Try common field names — we'll see what Widewail returns
            name    = (row.get("rowLabel") or row.get("location") or
                      row.get("name") or row.get("label") or "Unknown")
            reviews = (row.get("totalReviews") or row.get("reviewCount") or
                      row.get("reviews") or row.get("count") or "N/A")
            rating  = (row.get("rating") or row.get("averageRating") or
                      row.get("avgRating") or row.get("avg") or "N/A")

            stores.append({
                "store":      str(name),
                "reviews":    str(reviews),
                "avg_rating": str(rating)
            })

    print(f"Parsed {len(stores)} stores.")
    return stores


def build_email_html(stores):
    today     = datetime.now()
    month_str = today.strftime("%B")
    date_str  = today.strftime("%B %d, %Y")

    if stores:
        table_rows = ""
        for s in stores:
            try:
                r = float(s['avg_rating'])
                star = "⭐⭐⭐⭐⭐" if r >= 4.5 else "⭐⭐⭐⭐" if r >= 4.0 else "⭐⭐⭐" if r >= 3.0 else "⭐⭐"
            except:
                star = "⭐"
            table_rows += f"""
            <tr>
                <td style="padding:10px 14px;border-bottom:1px solid #eee">{s['store']}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #eee;text-align:center">{s['reviews']}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #eee;text-align:center">{s['avg_rating']} {star}</td>
            </tr>"""

        table_html = f"""
        <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px">
            <thead>
                <tr style="background-color:#4A90D9;color:white">
                    <th style="padding:12px 14px;text-align:left">Store</th>
                    <th style="padding:12px 14px;text-align:center">Reviews (MTD)</th>
                    <th style="padding:12px 14px;text-align:center">Avg Rating</th>
                </tr>
            </thead>
            <tbody>{table_rows}</tbody>
        </table>"""
    else:
        table_html = "<p><em>No store data could be retrieved. Please check Widewail manually.</em></p>"

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:0 auto">
        <p>Hey team! 👋</p>
        <p>Here's your <strong>Google Review snapshot for {month_str} month-to-date</strong> as of <strong>{date_str}</strong>:</p>
        {table_html}
        <br>
        <p>Keep up the amazing work — every review makes a difference! 🌟</p>
        <p>Feel free to reply with any questions or shoutouts.</p>
        <br>
        <p>Thanks,<br><strong>Justin</strong></p>
        <hr style="border:none;border-top:1px solid #eee;margin-top:30px">
        <p style="font-size:11px;color:#999">This report was automatically generated from Widewail · {date_str}</p>
    </body></html>"""


def send_email(html_body):
    print("Sending email via Gmail SMTP...")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Google - MTD"
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = "jcopenhaver@publicstorage.com"
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, "jcopenhaver@publicstorage.com", msg.as_string())
    print("Email sent successfully!")


def main():
    token  = get_auth_token()
    rows   = get_enterprise_reviews(token)
    stores = parse_stores(rows)
    html   = build_email_html(stores)
    send_email(html)


if __name__ == "__main__":
    main()
