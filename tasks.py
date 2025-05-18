import os
import re
import asyncio
import aiohttp
import openpyxl
from io import BytesIO
from dotenv import load_dotenv
from celery import Celery
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# Загрузка переменных среды
load_dotenv()

# Настройки Redis и Celery
REDIS_URL = os.getenv("REDIS_URL")
celery = Celery("tasks", broker=REDIS_URL)

# Настройки базы данных
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = scoped_session(sessionmaker(bind=engine))

# Только один вызов declarative_base
Base = declarative_base()

# Модели
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
    user_id = Column(Integer, ForeignKey("users.id"))  # user_id ссылается на users.id
    email = Column(String)

# Создание таблиц (если не существуют)
Base.metadata.create_all(bind=engine)

# Настройки фильтрации
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "cloudflare", "example.com", "no-reply", "noreply", "support", "admin", "localhost"]

# Получение HTML
async def fetch_html(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            return await response.text()
    except:
        return ""

# Извлечение email'ов
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

# Главная задача Celery
@celery.task
def collect_emails_to_file(user_id, urls, max_count):
    print(f"📥 Starte E-Mail-Sammlung für User {user_id}")
    db = SessionLocal()

    # Удаляем старые email'ы пользователя
    db.query(TempEmail).filter_by(user_id=user_id).delete()
    db.commit()

    emails = asyncio.run(extract_emails(urls))
    selected = emails[:max_count]
    print(f"📨 Gefundene E-Mails: {len(emails)}, verwendet: {len(selected)}")

    # Сохраняем в базу
    for email in selected:
        db.add(TempEmail(user_id=user_id, email=email))
    db.commit()

    # Также сохраняем в Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Emails"
    ws.append(["E-Mail"])
    for e in selected:
        ws.append([e])

    output_path = f"/tmp/emails_user_{user_id}.xlsx"
    wb.save(output_path)
    print(f"✅ Datei gespeichert: {output_path}")

    db.close()
