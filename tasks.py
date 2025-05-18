import os
import re
import asyncio
import aiohttp
import openpyxl
from io import BytesIO
from redis import Redis
from celery import Celery
from dotenv import load_dotenv
from email.message import EmailMessage
import smtplib

load_dotenv()

# Настройки Redis
REDIS_URL = os.getenv("REDIS_URL")
celery = Celery("tasks", broker=REDIS_URL)

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "no-reply", "noreply"]

async def fetch_html(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            return await response.text()
    except:
        return ""

async def extract_emails(urls):
    emails = set()
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        htmls = await asyncio.gather(*(fetch_html(session, url) for url in urls))
        for html in htmls:
            found = re.findall(EMAIL_REGEX, html)
            for email in found:
                if not any(bad in email for bad in EXCLUDE_DOMAINS):
                    emails.add(email)
    return list(emails)

def send_email(to_email, subject, body, attachment=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_USER")
    msg["To"] = to_email
    msg.set_content(body)

    if attachment:
        msg.add_attachment(attachment.getvalue(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename="emails.xlsx")

    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)

@celery.task
def collect_emails_to_file(user_id, urls, max_count):
    print(f"📥 Start collecting for user {user_id}")
    emails = asyncio.run(extract_emails(urls))
    selected = emails[:max_count]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Emails"
    ws.append(["E-Mail"])
    for e in selected:
        ws.append([e])

    output_path = f"/tmp/emails_user_{user_id}.xlsx"
    wb.save(output_path)
    print(f"✅ Saved Excel to {output_path}")
