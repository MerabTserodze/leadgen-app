import os
import re
import asyncio
import aiohttp
from dotenv import load_dotenv
from celery import Celery
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base

# --- Настройки
load_dotenv()
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

celery = Celery("tasks", broker=REDIS_URL)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --- Локальная модель (дублируем TempEmail)
class TempEmail(Base):
    __tablename__ = "temp_emails"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String)

# --- Email-фильтры
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "no-reply", "noreply"]

# --- HTML-фетчинг
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

# --- Celery-задача
@celery.task
def collect_emails_to_file(user_id, urls, max_count):
    print(f"📥 Starte E-Mail-Sammlung für User {user_id}")
    emails = asyncio.run(extract_emails(urls))
    selected = emails[:max_count]
    print(f"📊 Gefundene E-Mails: {len(emails)}, gespeichert: {len(selected)}")

    db = SessionLocal()
    try:
        db.query(TempEmail).filter_by(user_id=user_id).delete()
        for e in selected:
            db.add(TempEmail(user_id=user_id, email=e))
        db.commit()
        print(f"✅ Emails gespeichert für User {user_id}")
    except Exception as e:
        print(f"❌ Fehler beim Speichern in DB: {e}")
        db.rollback()
    finally:
        db.close()
