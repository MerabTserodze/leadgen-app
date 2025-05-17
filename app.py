from flask import Flask, render_template, request, redirect, send_file, session, jsonify
from dotenv import load_dotenv
from io import BytesIO
import json
import sqlite3
import hashlib
import dns.resolver
import openpyxl
import re
import asyncio
from urllib.parse import urljoin, urlparse
import aiohttp
import requests
import stripe
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
DOMAIN = os.getenv("DOMAIN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "/tmp/leadgen.db")

SERPAPI_KEY = "435924c0a06fc34cdaed22032ba6646be2d0db381a7cfff645593d77a7bd3dcd"
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
EXCLUDE_DOMAINS = ["sentry.io", "wixpress.com", "cloudflare", "example.com", "no-reply", "noreply", "localhost", "wordpress.com"]

# --- Утилиты

def has_mx_record(domain):
    try:
        return len(dns.resolver.resolve(domain, "MX")) > 0
    except:
        return False

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

def get_email_limit():
    user = get_current_user()
    if not user: return 0
    if user["plan"] == "starter":
        return 50
    elif user["plan"] == "profi":
        return float("inf")
    return 10

# --- Поисковые функции

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
        results = data.get("local_results", [])
        return [place.get("website") for place in results if place.get("website")]
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
        urls = []
        for result in data.get("organic_results", []):
            link = result.get("link", "")
            if not any(x in link for x in ["facebook.com", "youtube.com", "tripadvisor.com"]):
                urls.append(link)
        return urls
    except Exception as e:
        print("❌ Fehler bei get_google_results:", e)
        return []

# --- База данных

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            plan TEXT DEFAULT 'free'
        )
    """)
    conn.commit()
    conn.close()

def register_user(email, password):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, password_hash))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def login_user(email, password):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email=? AND password=?", (email, password_hash))
    user = cur.fetchone()
    conn.close()
    if user:
        session["user_id"] = user[0]
        return True
    return False

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, email, plan FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return {"id": user[0], "email": user[1], "plan": user[2]} if user else None

init_db()

# --- Роуты

@app.route("/")
def homepage():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if login_user(email, password):
            return redirect("/dashboard")
        return "Fehler: Ungültige Zugangsdaten."
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if register_user(email, password):
            return redirect("/login")
        return "Fehler: Registrierung fehlgeschlagen."
    return render_template("register.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    user = get_current_user()
    if not user:
        return redirect("/login")
    selected_plan = user["plan"]
    if request.method == "POST":
        error = "⚠️ Tarifänderung ist nur über Stripe erlaubt."
        return render_template("dashboard.html", selected_plan=selected_plan, error=error), 403
    return render_template("dashboard.html", selected_plan=selected_plan)

@app.route("/preise")
def preise():
    return render_template("preise.html")

@app.route("/emails", methods=["GET", "POST"])
def emails():
    results = []
    user = get_current_user()
    if not user:
        return redirect("/login")

    if request.method == "POST":
        try:
            keyword = request.form.get("keyword")
            location = request.form.get("location")
            radius_km = int(request.form.get("radius", 10))

            if user["plan"] == "free":
                return "❌ Dein Plan erlaubt keine E-Mail-Suche. Bitte upgraden."

            maps_urls = get_maps_results(keyword, location, radius_km)
            google_urls = get_google_results(keyword, location)
            urls = list(set(maps_urls + google_urls))
            urls = [url for url in urls if all(x not in url for x in [".pdf", ".jpg", ".png", ".zip", "/login", "/cart", "facebook.com", "youtube.com", "tripadvisor.com"])]
            urls = list(set(urls))[:50]

            all_emails = asyncio.run(extract_emails_from_url_async(urls))
            valid_emails = [e for e in all_emails if is_valid_email(e)]
            results = list(set(valid_emails))[:get_email_limit()]
            session["emails"] = results
        except Exception as e:
            import traceback
            traceback.print_exc()
            return "Ein Fehler ist aufgetreten beim Verarbeiten der Anfrage."
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

@app.route("/send")
def send():
    return render_template("send.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/subscribe/<plan>")
def subscribe(plan):
    prices = {
        "starter": "price_ТВОЙ_STARTER_ID",
        "profi": "price_ТВОЙ_PROFI_ID"
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
        if plan and user_id:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
            conn.commit()
            conn.close()
    return jsonify({"status": "success"}), 200

@app.route("/success")
def success():
    return "🎉 Zahlung erfolgreich! Tarif wird bald aktualisiert."

if __name__ != "__main__":
    gunicorn_app = app

if __name__ == "__main__":
    app.run(debug=True)
