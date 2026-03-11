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

        rows = data.get("_embedded", {}).get("rows", [])
        if not rows:
            print("No rows found in response.")
            break

        all_stores.extend(rows)

        page_info   = data.get("page", {})
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

            if isinstance(columns, list) and len(columns) > 0:
                col = columns[0]
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
    day_of_month = today.day

    # ── Compute group-level metrics ──────────────────────────────────────────
    ratings = []
    for s in stores:
        try:
            ratings.append(float(s['avg_rating']))
        except:
            pass
    group_avg = round(sum(ratings) / len(ratings), 1) if ratings else None

    numeric_stores = [s for s in stores if s['reviews'].isdigit()]
    total_reviews  = sum(int(s['reviews']) for s in numeric_stores)

    on_track  = [s for s in numeric_stores if int(s['reviews']) >= 2]
    need_work = [s for s in numeric_stores if int(s['reviews']) < 2]
    zero_reviews = [s for s in numeric_stores if int(s['reviews']) == 0]

    # Sort to find top and bottom performers
    sorted_by_reviews = sorted(numeric_stores, key=lambda s: int(s['reviews']), reverse=True)
    top_stores  = sorted_by_reviews[:3]   # top 3 by review count
    zero_stores = [s for s in sorted_by_reviews if int(s['reviews']) == 0]

    # Best rated store (min 1 review)
    rated_stores = [s for s in stores if s['avg_rating'] not in ('N/A', '') ]
    try:
        best_rated = max(rated_stores, key=lambda s: float(s['avg_rating']))
    except:
        best_rated = None

    pct_on_track = round(len(on_track) / len(numeric_stores) * 100) if numeric_stores else 0

    # ── Dynamic subject line ─────────────────────────────────────────────────
    # (used in send_email, returned from this function as a tuple)
    if group_avg is None:
        subject = f"Google MTD Review Report — {month_str}"
    elif group_avg >= 4.5:
        subject = f"🌟 {group_avg}⭐ Group Rating — Keep It Up! | Google MTD {month_str}"
    elif group_avg >= 4.0:
        subject = f"💪 {group_avg}⭐ Group Rating — Push for 4.5! | Google MTD {month_str}"
    else:
        subject = f"🚨 {group_avg}⭐ Group Rating — We Need to Rally! | Google MTD {month_str}"

    # ── Dynamic opening ──────────────────────────────────────────────────────
    if pct_on_track >= 80:
        opening = f"<p>Good Morning My Peeps! 🎉</p><p>Big shoutout — <strong>{pct_on_track}% of stores are already on track</strong> with 2+ reviews this month. That's the energy we need! Let's close out {month_str} strong. 🚀</p>"
    elif pct_on_track >= 50:
        opening = f"<p>Good Morning My Peeps! 👋</p><p>We're making progress — <strong>{pct_on_track}% of stores are on track</strong> with 2+ reviews so far in {month_str}. The other half needs to pick it up — we've still got time, but the clock is ticking. ⏰</p>"
    else:
        opening = f"<p>Good Morning My Peeps! 👋</p><p>We need to talk. Only <strong>{pct_on_track}% of stores have 2+ reviews</strong> this month in {month_str}. That is not where we need to be — it's time to get after it. 🔥</p>"

    # ── Dynamic group rating commentary ─────────────────────────────────────
    if group_avg is None:
        rating_line = "<p>Group rating data is unavailable this week — please check Widewail directly.</p>"
    elif group_avg >= 4.7:
        rating_line = f"<p>Our group rating is sitting at a <strong>{group_avg} ⭐</strong> — that is absolutely elite. Let's protect it and keep pushing! 🏆</p>"
    elif group_avg >= 4.5:
        rating_line = f"<p>We're at a <strong>{group_avg} ⭐ group rating</strong> — that's excellent. One more push and we can hit 4.7+. Every 5-star review counts! ⭐</p>"
    elif group_avg >= 4.2:
        rating_line = f"<p>Group rating is at <strong>{group_avg} ⭐</strong> — so close to 4.5. A strong week of 5-star reviews could get us there. Don't let up! 💪</p>"
    elif group_avg >= 4.0:
        rating_line = f"<p>We're at <strong>{group_avg} ⭐</strong> as a group — right at the 4-star line. We need quality AND quantity. Every perfect experience is a chance to ask for a 5-star review. 🎯</p>"
    else:
        rating_line = f"<p>⚠️ Group rating is at <strong>{group_avg} ⭐</strong> — that's below where we need to be. We need more volume AND higher quality reviews to move this number. Let's focus up. 🚨</p>"

    # ── Dynamic review volume commentary ────────────────────────────────────
    reviews_per_day = round(total_reviews / day_of_month, 1) if day_of_month > 0 else 0
    volume_line = f"<p>We've collected <strong>{total_reviews} total reviews</strong> across all stores so far in {month_str} ({reviews_per_day}/day pace). "
    target_mtd  = len(numeric_stores) * 4  # 4 reviews per store as rough monthly target
    if total_reviews >= target_mtd:
        volume_line += f"We're ahead of pace toward our group target — keep it rolling! 🟢</p>"
    elif total_reviews >= target_mtd * 0.7:
        volume_line += f"We're on pace but need to stay consistent to hit our group target. 🟡</p>"
    else:
        volume_line += f"We're behind pace for the month — every store needs to make asking a daily habit. 🔴</p>"

    # ── Top performers shoutout ──────────────────────────────────────────────
    if top_stores:
        top_lines = ", ".join([f"<strong>{s['store']}</strong> ({s['reviews']} reviews)" for s in top_stores])
        top_section = f"<p>🏅 <strong>Leading the pack this month:</strong> {top_lines} — that's how it's done!</p>"
    else:
        top_section = ""

    # ── Stores needing help ──────────────────────────────────────────────────
    if zero_stores:
        zero_names = ", ".join([f"<strong>{s['store']}</strong>" for s in zero_stores])
        zero_section = f"<p>🚨 <strong>Zero reviews so far in {month_str}:</strong> {zero_names} — not a single one. This needs to change today. Ask every customer. Every. Single. One.</p>"
    else:
        zero_section = ""

    if need_work and not zero_stores:
        need_names = ", ".join([f"<strong>{s['store']}</strong>" for s in need_work])
        need_section = f"<p>⚠️ <strong>Under 2 reviews:</strong> {need_names} — you're behind. Time to pick up the pace! 🔥</p>"
    elif need_work and zero_stores:
        remaining_need = [s for s in need_work if s not in zero_stores]
        if remaining_need:
            need_names = ", ".join([f"<strong>{s['store']}</strong>" for s in remaining_need])
            need_section = f"<p>⚠️ <strong>Also under 2 reviews:</strong> {need_names} — let's get moving! 🔥</p>"
        else:
            need_section = ""
    else:
        need_section = f"<p>✅ Every store has at least 2 reviews this month — amazing effort across the board!</p>"

    # ── Best rated store callout ─────────────────────────────────────────────
    if best_rated:
        try:
            br = float(best_rated['avg_rating'])
            if br >= 4.8:
                best_rated_section = f"<p>⭐ <strong>{best_rated['store']}</strong> is leading on quality with a <strong>{best_rated['avg_rating']} rating</strong> — that's what great service looks like!</p>"
            else:
                best_rated_section = ""
        except:
            best_rated_section = ""
    else:
        best_rated_section = ""

    # ── Build the store table ────────────────────────────────────────────────
    if stores:
        table_rows = ""
        for s in stores:
            try:
                r    = float(s['avg_rating'])
                star = "⭐⭐⭐⭐⭐" if r >= 4.5 else "⭐⭐⭐⭐" if r >= 4.0 else "⭐⭐⭐" if r >= 3.0 else "⭐⭐"
            except:
                star = "⭐"
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

    # ── Assemble final HTML ──────────────────────────────────────────────────
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:0 auto">
        {opening}

        <p>Here's your <strong>Google Review snapshot for {month_str} month-to-date</strong> as of <strong>{date_str}</strong>. Every store should be pushing for <strong>4+ reviews</strong> this month — let's get after it! 🚀</p>

        {table_html}

        <br>
        {rating_line}
        {volume_line}
        {top_section}
        {best_rated_section}
        {zero_section}
        {need_section}

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

    return html, subject


def send_email(html_body, subject):
    print("Sending email via Gmail SMTP...")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = "jcopenhaver@publicstorage.com"
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, "jcopenhaver@publicstorage.com", msg.as_string())
    print("Email sent successfully!")


def main():
    token        = get_auth_token()
    rows         = get_enterprise_reviews(token)
    stores       = parse_stores(rows)
    html, subject = build_email_html(stores)
    send_email(html, subject)


if __name__ == "__main__":
    main()
