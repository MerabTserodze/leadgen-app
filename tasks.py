import os
import re
import asyncio
import aiohttp
import openpyxl
import ssl
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
celery = Celery(
    "tasks",
    broker=REDIS_URL,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE}
)

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

class SeenEmail(Base):
    __tablename__ = "seen_emails"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String)

Base.metadata.create_all(bind=engine)

# --- Фильтры
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "no-reply", "noreply", "support", "admin", "localhost"]
COMMON_PATHS = ["/kontakt", "/impressum", "/about", "/ueber-uns", "/info", "/contact"]

# --- Получение HTML с сайта
async def fetch_html(session, url, retries=2):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке {url}: {e}")
            await asyncio.sleep(1)
    return ""

# --- Извлечение email-ов с множества URL
async def extract_emails_from_url_async(urls):
    collected_emails = set()
    headers = {"User-Agent": "Mozilla/5.0"}

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for url in urls:
            base_url = url.rstrip("/")
            extended_urls = [base_url + path for path in COMMON_PATHS]
            all_urls = [base_url] + extended_urls
            for u in all_urls:
                tasks.append(fetch_html(session, u))

        responses = await asyncio.gather(*tasks)
        for html in responses:
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            text_emails = re.findall(EMAIL_REGEX, soup.get_text())
            collected_emails.update(text_emails)
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if "mailto:" in href:
                    email = href.split("mailto:")[1].split("?")[0]
                    collected_emails.add(email)

    filtered = [
        email for email in collected_emails
        if not any(bad in email for bad in EXCLUDE_DOMAINS)
    ]
    return list(set(filtered))

# --- Главная задача Celery
@celery.task(
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=5
)
def collect_emails_to_file(self, user_id, urls, max_count):
    print(f"📥 Начало сбора email'ов для пользователя {user_id}")
    print(f"🔗 URL-ов передано: {len(urls)} — {urls}")

    db = SessionLocal()

    try:
        db.query(TempEmail).filter_by(user_id=user_id).delete()
        db.commit()

        try:
            emails = asyncio.run(extract_emails_from_url_async(urls))
        except Exception as e:
            print(f"❌ Ошибка при сборе email'ов: {e}")
            emails = []

        print(f"📨 Найдено email'ов: {len(emails)}")
        print(f"💡 Список email'ов: {emails}")

        seen_emails = set(row[0] for row in db.query(SeenEmail.email).filter_by(user_id=user_id).all())
        new_emails = [e for e in emails if e not in seen_emails]

        print(f"🧹 Уникальные email'ы: {len(new_emails)}")

        selected = new_emails[:max_count]

        for email in selected:
            db.add(TempEmail(user_id=user_id, email=email))
            db.add(SeenEmail(user_id=user_id, email=email))

        db.commit()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Emails"
        ws.append(["E-Mail"])
        for e in selected:
            ws.append([e])

        output_path = f"/tmp/emails_user_{user_id}.xlsx"
        wb.save(output_path)
        print(f"✅ Excel-файл сохранён: {output_path}")

    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка в основной транзакции: {e}")
        raise self.retry(exc=e)

    finally:
        db.close()
