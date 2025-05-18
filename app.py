from flask import Flask, render_template, request, redirect, send_file, session, jsonify
from dotenv import load_dotenv
from io import BytesIO
import hashlib
import dns.resolver
import openpyxl
import re
import asyncio
import aiohttp
import requests
import stripe
import os
import bcrypt
import smtplib
from tasks import collect_and_send_emails
from email.message import EmailMessage
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import IntegrityError

# --- Загрузка настроек
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
DOMAIN = os.getenv("DOMAIN")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

# --- SQLAlchemy модели
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    plan = Column(String, default="free")
    requests_used = Column(Integer, default=0)
    is_admin = Column(Integer, default=0)

class SeenEmail(Base):
    __tablename__ = "seen_emails"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String)

class History(Base):
    __tablename__ = "history"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    keyword = Column(String)
    location = Column(String)
    searched_at = Column(DateTime, default=datetime.utcnow)

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print("ℹ️ Fehler beim Erstellen der Tabellen:", e)
# --- Утилиты
SERPAPI_KEY = "435924c0a06fc34cdaed22032ba6646be2d0db381a7cfff645593d77a7bd3dcd"
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "wixpress.com", "cloudflare", "example.com", "no-reply", "noreply", "localhost", "wordpress.com"]

def has_mx_record(domain):
    try:
        return len(dns.resolver.resolve(domain, "MX")) > 0
    except:
        return False
        
def send_email(to_email, subject, content):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_USER")
    msg["To"] = to_email
    msg.set_content(content)

    try:
        with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
            server.starttls()
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            server.send_message(msg)
    except Exception as e:
        print("❌ Fehler beim Senden der E-Mail:", e)



def is_valid_email(email):
    email = email.lower()
    BAD_PATTERNS = ["noreply", "no-reply", "support", "admin"]
    if any(p in email for p in BAD_PATTERNS): return False
    if any(d in email for d in EXCLUDE_DOMAINS): return False
    domain = email.split("@")[-1]
    return has_mx_record(domain)

async def fetch_html(session, url, retries=3):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=10) as response:
                return await response.text()
        except:
            await asyncio.sleep(2 ** attempt)
    return ""

async def extract_emails_from_url_async(urls):
    collected_emails = set()
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [fetch_html(session, url) for url in urls]
        responses = await asyncio.gather(*tasks)
        for html in responses:
            emails = re.findall(EMAIL_REGEX, html)
            collected_emails.update(emails)
    return list(collected_emails)

# --- Поиск

def get_maps_results(keyword, location, radius_km=10):
    params = {
        "engine": "google_maps",
        "type": "search",
        "q": keyword,
        "location": location,
        "hl": "de",
        "gl": "de",
        "google_domain": "google.de",
        "api_key": SERPAPI_KEY,
        "num": 50,
        "radius": radius_km * 1000
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()
        return [place.get("website") for place in data.get("local_results", []) if place.get("website")]
    except Exception as e:
        print("❌ Fehler bei get_maps_results:", e)
        return []

def get_google_results(keyword, location):
    query = f"{keyword} {location} kontakt email impressum site:.de"
    params = {
        "engine": "google",
        "q": query,
        "location": location,
        "hl": "de",
        "gl": "de",
        "google_domain": "google.de",
        "api_key": SERPAPI_KEY,
        "num": 50
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()
        urls = [r.get("link") for r in data.get("organic_results", []) if r.get("link") and not any(x in r.get("link") for x in ["facebook.com", "youtube.com", "tripadvisor.com"])]
        return urls
    except Exception as e:
        print("❌ Fehler bei get_google_results:", e)
        return []

# --- Аутентификация

def register_user(email, password):
    db = SessionLocal()
    try:
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user = User(email=email, password=hashed.decode('utf-8'))
        db.add(user)
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    finally:
        db.close()

def login_user(email, password):
    db = SessionLocal()
    user = db.query(User).filter_by(email=email).first()
    db.close()
    if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
        session["user_id"] = user.id
        return True
    return False

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = SessionLocal()
    user = db.query(User).filter_by(id=user_id).first()
    db.close()
    return user

def get_user_limits():
    user = get_current_user()
    if not user:
        return {"requests": 0, "emails": 0}
    limits = {
        "free": {"requests": 3, "emails": 10},
        "starter": {"requests": 30, "emails": 30},
        "profi": {"requests": 80, "emails": 50}
    }
    return limits.get(user.plan, {"requests": 0, "emails": 0})

# --- Маршруты
@app.route("/")
def homepage():
    return render_template("home.html")

@app.route("/admin")
def admin_panel():
    user = get_current_user()
    if not user or not user.is_admin:
        return redirect("/login")

    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return render_template("admin.html", users=users)



@app.route("/admin/toggle_admin", methods=["POST"])
def toggle_admin():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    user_id = data.get("user_id")
    db = SessionLocal()
    target = db.query(User).filter_by(id=user_id).first()
    if target:
        target.is_admin = not target.is_admin
        db.commit()
    db.close()
    return jsonify({"status": "success"})

@app.route("/admin/delete_user", methods=["POST"])
def delete_user():
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    user_id = data.get("user_id")
    db = SessionLocal()
    target = db.query(User).filter_by(id=user_id).first()
    if target:
        db.delete(target)
        db.commit()
    db.close()
    return jsonify({"status": "deleted"})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        if register_user(email, password):
            send_email(
                to_email=email,
                subject="Willkommen bei LeadGen",
                content="Vielen Dank für deine Registrierung! Du kannst dich jetzt einloggen."
            )
            return redirect("/login")
        else:
            return "Fehler: Registrierung fehlgeschlagen."
            
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if login_user(email, password):
            return redirect("/dashboard")
        return "Fehler: Ungültige Zugangsdaten."
    return render_template("login.html")
    
@app.route("/admin/update_plan", methods=["POST"])
def update_plan():
    user = get_current_user()
    if not user or not getattr(user, "is_admin", False):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    user_id = data.get("user_id")
    new_plan = data.get("plan")

    db = SessionLocal()
    target_user = db.query(User).filter_by(id=user_id).first()
    if target_user:
        target_user.plan = new_plan
        db.commit()
        db.close()
        return jsonify({"success": True})
    else:
        db.close()
        return jsonify({"error": "User not found"}), 404


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/dashboard")
def dashboard():
    user = get_current_user()
    if not user:
        return redirect("/login")
    limits = get_user_limits()
    remaining = max(limits["requests"] - user.requests_used, 0)
    return render_template("dashboard.html", selected_plan=user.plan, user=user, request_limit=limits["requests"], request_limit_display=limits["requests"], requests_remaining=remaining, is_unlimited=False)

@app.route("/preise")
def preise():
    return render_template("preise.html")

@app.route("/emails", methods=["GET", "POST"])
def emails():
    results = []
    user = get_current_user()
    if not user:
        return redirect("/login")
    limits = get_user_limits()
    max_requests = limits["requests"]
    max_emails = limits["emails"]
    db = SessionLocal()
    if request.method == "POST":
        if user.requests_used >= max_requests:
            return "❌ Du hast dein Anfrage-Limit erreicht."
        keyword = request.form.get("keyword", "").strip()
        location = request.form.get("location", "").strip()
        radius_km = int(request.form.get("radius", 10))
        maps_urls = get_maps_results(keyword, location, radius_km)
        google_urls = get_google_results(keyword, location)
        urls = list(set(maps_urls + google_urls))
        urls = [url for url in urls if all(x not in url for x in [".pdf", ".jpg", ".png", ".zip", "/login", "/cart", "facebook.com", "youtube.com", "tripadvisor.com"])]
        urls = urls[:50]
        all_emails = asyncio.run(extract_emails_from_url_async(urls))
        valid_emails = [e for e in all_emails if is_valid_email(e)]
        seen = {row.email for row in db.query(SeenEmail).filter_by(user_id=user.id).all()}
        fresh_emails = [e for e in valid_emails if e not in seen]
        results = list(set(fresh_emails))[:max_emails]
        collect_and_send_emails.delay(user.email, urls, max_emails)

        for email in results:
            db.add(SeenEmail(user_id=user.id, email=email))

        user.requests_used += 1
        db.add(History(user_id=user.id, keyword=keyword, location=location))
        db.commit()
        db.close()

        return "✅ Deine Anfrage wird im Hintergrund verarbeitet."
        for email in results:
            db.add(SeenEmail(user_id=user.id, email=email))
        user.requests_used += 1
        db.add(History(user_id=user.id, keyword=keyword, location=location))
        db.commit()
    db.close()
    return render_template("emails.html", results=results)

@app.route("/export")
def export():
    emails = session.get("emails", [])
    if not emails:
        return "Keine Daten zum Exportieren."
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "E-Mails"
    ws.append(["E-Mail-Adresse"])
    for email in emails:
        ws.append([email])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name="emails.xlsx", as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/subscribe/<plan>")
def subscribe(plan):
    prices = {
        "starter": "price_1RP8Ah2YuXttkrNbVuSRwuhu",
        "profi": "price_1RP8Bw2YuXttkrNbZUPVMUUQ"
    }
    if plan not in prices:
        return "Ungültiger Plan", 400
    checkout_session = stripe.checkout.Session.create(
        success_url=DOMAIN + "/success",
        cancel_url=DOMAIN + "/preise",
        payment_method_types=["sepa_debit"],
        mode="subscription",
        line_items=[{"price": prices[plan], "quantity": 1}],
        metadata={"plan": plan, "user_id": session.get("user_id")}
    )
    return redirect(checkout_session.url, code=303)

@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        return "⚠️ Invalid signature", 400
    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        plan = session_data["metadata"].get("plan")
        user_id = session_data["metadata"].get("user_id")
        db = SessionLocal()
        user = db.query(User).filter_by(id=user_id).first()
        if user and plan:
            user.plan = plan
            db.commit()
        db.close()
    return jsonify({"status": "success"}), 200

@app.route("/success")
def success():
    return "🎉 Zahlung erfolgreich! Tarif wird bald aktualisiert."

if __name__ == "__main__":
    app.run(debug=True)
