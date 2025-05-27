import os
import re
import ssl
import asyncio
import aiohttp
import openpyxl
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from celery import Celery
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

# --- Загрузка переменных среды
load_dotenv()

# --- Настройки Redis и Celery
REDIS_URL = os.getenv("REDIS_URL")
celery = Celery("tasks", broker=REDIS_URL, broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE})

# --- Настройки базы данных
DATABASE_URL = os.getenv("DATABASE_URL")
if "sslmode" not in DATABASE_URL:
    DATABASE_URL += "?sslmode=require"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

# --- Модели
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    plan = Column(String, default="free")
    requests_used = Column(Integer, default=0)
    is_admin = Column(Integer, default=0)

class TempEmail(Base):
    __tablename__ = "temp_emails"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String)

class TempPhone(Base):
    __tablename__ = "temp_phones"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    phone = Column(String)

class SeenEmail(Base):
    __tablename__ = "seen_emails"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String)

Base.metadata.create_all(bind=engine)

# --- Фильтры
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"(\+?\d[\d\s\-\(\)]{7,}\d)"
EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "noreply", "no-reply", "support", "admin", "localhost"]
COMMON_PATHS = ["/kontakt", "/impressum", "/about", "/ueber-uns", "/info", "/contact"]

# --- Celery Task
@celery.task(
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5
)
def collect_emails_to_file(self, user_id, urls, max_count):
    async def fetch_html(session, url, retries=2):
        for attempt in range(retries):
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
            except:
                await asyncio.sleep(1)
        return ""

    async def extract_contacts(urls):
        results = []
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = []
            for url in urls:
                base = url.rstrip("/")
                extended = [base + path for path in COMMON_PATHS]
                all_urls = [base] + extended
                for u in all_urls:
                    tasks.append((u, fetch_html(session, u)))

            responses = await asyncio.gather(*[t[1] for t in tasks])
            urls_checked = [t[0] for t in tasks]

            for html, page_url in zip(responses, urls_checked):
                if not html:
                    continue

                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(separator=" ", strip=True)

                emails = re.findall(EMAIL_REGEX, text)
                phones = re.findall(PHONE_REGEX, text)

                clean_emails = {
                    e.strip() for e in emails
                    if not any(bad in e for bad in EXCLUDE_DOMAINS)
                }

                clean_phones = {
                    p.strip() for p in phones
                    if len(p.strip()) >= 6
                }

                if clean_emails or clean_phones:
                    results.append({
                        "website": page_url,
                        "emails": list(clean_emails),
                        "phones": list(clean_phones)
                    })
        return results

    # --- Работа с БД
    print(f"📥 Сбор данных для user_id={user_id}")
    db = SessionLocal()
    try:
        db.query(TempEmail).filter_by(user_id=user_id).delete()
        db.query(TempPhone).filter_by(user_id=user_id).delete()
        db.commit()

        contacts = asyncio.run(extract_contacts(urls))

        seen_emails = set(row[0] for row in db.query(SeenEmail.email).filter_by(user_id=user_id).all())
        selected = []

        for contact in contacts:
            for email in contact["emails"]:
                if email not in seen_emails:
                    db.add(TempEmail(user_id=user_id, email=email))
                    db.add(SeenEmail(user_id=user_id, email=email))
                    seen_emails.add(email)

            for phone in contact["phones"]:
                db.add(TempPhone(user_id=user_id, phone=phone))

            if contact["emails"]:
                selected.append({
                    "website": contact["website"],
                    "emails": contact["emails"],
                    "phones": contact["phones"]
                })

        db.commit()

        # --- Excel файл
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Contacts"
        ws.append(["Website", "Email", "Phone"])

        written = 0
        for item in selected:
            for email in item["emails"]:
                phones = item["phones"] or [""]
                for phone in phones:
                    if written < max_count:
                        ws.append([item["website"], email, phone])
                        written += 1

        path = f"/tmp/emails_user_{user_id}.xlsx"
        wb.save(path)
        print(f"✅ Excel сохранён: {path}")

    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка в задаче: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()
