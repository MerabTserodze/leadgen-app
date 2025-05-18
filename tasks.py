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
    import re
    from bs4 import BeautifulSoup
    import aiohttp
    import asyncio

    EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    PHONE_REGEX = r"(\+?\d[\d\s\-\(\)]{7,}\d)"
    headers = {"User-Agent": "Mozilla/5.0"}

    COMMON_PATHS = ["/kontakt", "/impressum", "/about", "/ueber-uns", "/info", "/contact"]
    EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "noreply", "no-reply", "support", "admin", "localhost"]

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

                clean_emails = set()
                for e in emails:
                    e = e.strip().replace("\n", "").replace("\r", "").replace("\xa0", "")
                    if not any(bad in e for bad in EXCLUDE_DOMAINS):
                        clean_emails.add(e)

                clean_phones = set(p.strip() for p in phones if len(p.strip()) > 6)

                if clean_emails or clean_phones:
                    results.append({
                        "website": page_url,
                        "emails": list(clean_emails),
                        "phones": list(clean_phones)
                    })

        return results

    # --- Выполнение парсинга
    print(f"📥 Сбор контактов для пользователя {user_id}")
    db = SessionLocal()

    try:
        db.query(TempEmail).filter_by(user_id=user_id).delete()
        db.commit()

        contacts = asyncio.run(extract_contacts(urls))

        seen_emails = set(row[0] for row in db.query(SeenEmail.email).filter_by(user_id=user_id).all())
        new_rows = []

        for item in contacts:
            for email in item["emails"]:
                if email not in seen_emails:
                    new_rows.append({
                        "website": item["website"],
                        "email": email,
                        "phones": item["phones"]
                    })
                    db.add(TempEmail(user_id=user_id, email=email))
                    db.add(SeenEmail(user_id=user_id, email=email))
                    seen_emails.add(email)

        db.commit()
        selected = new_rows[:max_count]

        # --- Excel файл
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Contacts"
        ws.append(["Website", "Email", "Phone"])

        for row in selected:
            phones = row["phones"] or [""]
            for phone in phones:
                ws.append([row["website"], row["email"], phone])

        output_path = f"/tmp/emails_user_{user_id}.xlsx"
        wb.save(output_path)
        print(f"✅ Excel-файл готов: {output_path}")

    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка: {e}")
        raise self.retry(exc=e)

    finally:
        db.close()
