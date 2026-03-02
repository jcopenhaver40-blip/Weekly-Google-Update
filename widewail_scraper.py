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

        # Extract rows from _embedded.rows
        rows = data.get("_embedded", {}).get("rows", [])

        if not rows:
            print("No rows found in response.")
            break

        all_stores.extend(rows)

        # Check pagination
        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        print(f"Page {page+1} of {total_pages}")
        if page + 1 >= total_pages:
            break

        page += 1

    print(f"Total rows fetched: {len(all_stores)}")
    return all_stores


def parse_stores(all_rows):
    stores = []
    if not all_rows:
        return stores

    try:
        for row in all_rows:
            name    = row.get("label", "Unknown")
            columns = row.get("columns", [])

            reviews = "N/A"
            rating  = "N/A"

            # columns is a list of dicts — find the right one
            if isinstance(columns, list) and len(columns) > 0:
                col = columns[0]  # First column has the main data
                reviews = col.get("totalReviews", "N/A")
                raw_rating = col.get("rating", "N/A")
                try:
                    rating = round(float(raw_rating), 1)
                except:
                    rating = raw_rating

            print(f"Store: {name} | Reviews: {reviews} | Rating: {rating}")
            stores.append({
                "store":      str(name),
                "reviews":    str(reviews),
                "avg_rating": str(rating)
            })

    except Exception as e:
        print(f"Parse error: {e}")

    print(f"Parsed {len(stores)} stores.")
    return stores


def build_email_html(stores):
    today     = datetime.now()
    month_str = today.strftime("%B")
    date_str  = today.strftime("%B %d, %Y")

    # Calculate group average rating
    ratings = []
    for s in stores:
        try:
            ratings.append(float(s['avg_rating']))
        except:
            pass
    group_avg = round(sum(ratings) / len(ratings), 1) if ratings else "N/A"

    # Split stores into on track (2+ reviews) and need to get going (0-1 reviews)
    on_track   = [s for s in stores if s['reviews'].isdigit() and int(s['reviews']) >= 2]
    need_work  = [s for s in stores if s['reviews'].isdigit() and int(s['reviews']) < 2]
    on_track  += [s for s in stores if not s['reviews'].isdigit()]

    if stores:
        table_rows = ""
        for s in stores:
            try:
                r = float(s['avg_rating'])
                star = "⭐⭐⭐⭐⭐" if r >= 4.5 else "⭐⭐⭐⭐" if r >= 4.0 else "⭐⭐⭐" if r >= 3.0 else "⭐⭐"
            except:
                star = "⭐"
            # Highlight stores with 0-1 reviews in light red
            try:
                row_style = "background-color:#fff3f3;" if int(s['reviews']) < 2 else ""
            except:
                row_style = ""
            table_rows += f"""
            <tr style="{row_style}">
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
        </table>
        <p style="font-size:12px;color:#999;margin-top:8px">🔴 Highlighted stores have fewer than 2 reviews this month</p>"""
    else:
        table_html = "<p><em>No store data could be retrieved. Please check Widewail manually.</em></p>"

    # Build shoutout lines
    need_work_names = ", ".join([s['store'] for s in need_work]) if need_work else None
    on_track_names  = ", ".join([s['store'] for s in on_track]) if on_track else None

    grind_line = f"<p>To all my homies with 2+ reviews — <strong>you are on track, keep grinding! 💪</strong></p>" if on_track else ""
    wake_line  = f"<p>⚠️ <strong>{need_work_names}</strong> — it's time to wake up and start grinding out some reviews!!! Leeetttssss gooooooo!!! 🔥</p>" if need_work_names else ""

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:0 auto">
        <p>Good Morning My Peeps! 👋</p>
        <p>Here's your <strong>Google Review snapshot for {month_str} month-to-date</strong> as of <strong>{date_str}</strong>. Every store should be pushing for <strong>4+ reviews</strong> — let's get after it! 🚀</p>

        {table_html}

        <br>
        <p>We are currently at a <strong>{group_avg} ⭐ group rating</strong> — let's keep fighting to push that number up!</p>

        {grind_line}
        {wake_line}

        <p><strong>Why It Matters:</strong> Google reviews help us attract new customers, improve our local search rankings, and showcase the great service you provide every day.</p>

        <p><strong>How to Get There:</strong><br>
        • Ask at the right moment — after a smooth move-in or when a customer seems happy<br>
        • Make it easy — use the QR code on your lease presentation script<br>
        • Be genuine — a simple <em>"We'd love if you could share your 5 Star experience on Google"</em> goes a long way</p>

        <p>Ask, ask, ASK!!! 🙌</p>

        <p>Thanks everyone,<br><strong>Justin</strong></p>
        <hr style="border:none;border-top:1px solid #eee;margin-top:30px">
        <p style="font-size:11px;color:#999">Auto-generated from Widewail · {date_str}</p>
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
