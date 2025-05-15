from flask import Flask, render_template, request, redirect, send_file, session
from io import BytesIO
import dns.resolver
import openpyxl
import re
import asyncio
from urllib.parse import urljoin, urlparse
import aiohttp
import requests

app = Flask(__name__)
app.secret_key = "supersecretkey"

SERPAPI_KEY = "435924c0a06fc34cdaed22032ba6646be2d0db381a7cfff645593d77a7bd3dcd"

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

EXCLUDE_DOMAINS = [
    "sentry.io", "wixpress.com", "cloudflare", "example.com",
    "no-reply", "noreply", "localhost", "wordpress.com"
]

def has_mx_record(domain):
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except:
        return False

def is_valid_email(email):
    email = email.lower()
    BAD_PATTERNS = ["noreply", "no-reply", "support", "admin"]

    if any(p in email for p in BAD_PATTERNS):
        return False

    for d in EXCLUDE_DOMAINS:
        if d in email:
            return False

    domain = email.split("@")[-1]
    return has_mx_record(domain)

async def fetch_html(session, url, retries=3):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=10) as response:
                return await response.text()
        except Exception:
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
    plan = session.get("plan", "free")
    if plan == "starter":
        return 50
    elif plan == "profi":
        return float("inf")
    return 10

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
        urls = [place.get("website") for place in results if place.get("website")]
        return urls
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
            if any(x in link for x in ["facebook.com", "youtube.com", "tripadvisor.com"]):
                continue
            urls.append(link)
        return urls
    except Exception as e:
        print("❌ Fehler bei get_google_results:", e)
        return []
def init_db():
    conn = sqlite3.connect("leadgen.db")
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

init_db()  # запускается при старте


@app.route("/")
def homepage():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        return redirect("/dashboard")
    return render_template("register.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    selected_plan = session.get("plan", "free")  # по умолчанию
    if request.method == "POST":
        selected_plan = request.form.get("plan")
        session["plan"] = selected_plan
    return render_template("dashboard.html", selected_plan=selected_plan)


@app.route("/preise")
def preise():
    return render_template("preise.html")

@app.route("/emails", methods=["GET", "POST"])
def emails():
    results = []
    if request.method == "POST":
        try:
            keyword = request.form.get("keyword")
            location = request.form.get("location")
            radius_km = int(request.form.get("radius", 10))

            maps_urls = get_maps_results(keyword, location, radius_km)
            google_urls = get_google_results(keyword, location)
            urls = list(set(maps_urls + google_urls))

            def is_valid_url(url):
                return all(x not in url for x in [".pdf", ".jpg", ".png", ".zip", "/login", "/cart", "facebook.com", "youtube.com", "tripadvisor.com"])

            urls = [url for url in urls if is_valid_url(url)]
            urls = list(set(urls))[:50]

            print(f"🔍 {len(urls)} URLs nach Filter.")

            all_emails = asyncio.run(extract_emails_from_url_async(urls))
            valid_emails = [e for e in all_emails if is_valid_email(e)]
            results = list(set(valid_emails))[:get_email_limit()]
            session["emails"] = results
        except Exception as e:
            print("❌ Gesamtfehler beim Suchen:", e)
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

    return send_file(
        output,
        download_name="emails.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/send")
def send():
    return render_template("send.html")

if __name__ != "__main__":
    gunicorn_app = app

if __name__ == "__main__":
    app.run(debug=True)
