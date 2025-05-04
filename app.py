from flask import Flask, render_template, request, redirect, send_file, session
from io import BytesIO
import dns.resolver
import openpyxl
import requests
import re
from bs4 import BeautifulSoup

app = Flask(__name__)

app.secret_key = "supersecretkey"

# === SerpAPI API-Key ===
SERPAPI_KEY = "435924c0a06fc34cdaed22032ba6646be2d0db381a7cfff645593d77a7bd3dcd"
def has_mx_record(domain):
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except:
        return False
# === Email-поиск по URL ===
def extract_emails_from_url(base_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        visited = set()
        collected_emails = set()

        # 1. Проверка главной страницы
        html = requests.get(base_url, timeout=5, headers=headers).text
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
        collected_emails.update(emails)
        visited.add(base_url)

        # 2. Если ничего не найдено — проверить вложенные страницы
        if not collected_emails:
            common_paths = ["/kontakt", "/impressum", "/contact", "/about"]
            for path in common_paths:
                full_url = base_url.rstrip("/") + path
                if full_url not in visited:
                    try:
                        sub_html = requests.get(full_url, timeout=5, headers=headers).text
                        sub_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", sub_html)
                        collected_emails.update(sub_emails)
                    except:
                        pass

        return list(collected_emails)

    except Exception as e:
        print("Fehler beim Parsen:", e)
        return []

        EXCLUDE_DOMAINS = [
    "sentry.io", "wixpress.com", "cloudflare", "example.com",
    "no-reply", "noreply", "localhost", "wordpress.com"
]

def is_valid_email(email):
    EXCLUDE_DOMAINS = [
        "sentry.io", "wixpress.com", "cloudflare", "example.com",
        "no-reply", "noreply", "localhost", "wordpress.com"
    ]

    for d in EXCLUDE_DOMAINS:
        if d in email.lower():
            return False

    # Проверка MX-записи
    domain = email.split("@")[-1]
    return has_mx_record(domain)


def get_email_limit():
    plan = session.get("plan", "free")  # по умолчанию бесплатно
    if plan == "starter":
        return 50
    elif plan == "profi":
        return float("inf")
    return 10

def get_maps_results(keyword, location, radius_km):
    params = {
        "engine": "google_maps",
        "q": keyword,
        "location": location,
        "hl": "de",
        "type": "search",
        "api_key": SERPAPI_KEY,
        "google_domain": "google.de",
        "radius": radius_km * 1000  # km → meter
    }

    response = requests.get("https://serpapi.com/search", params=params)
    data = response.json()

    urls = []
    if "local_results" in data:
        for place in data["local_results"]:
            website = place.get("website")
            if website:
                urls.append(website)
    return urls


# === Получение сайтов из Google через SerpAPI ===
def get_google_results(query):
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 10,
        "hl": "de"
    }
    response = requests.get("https://serpapi.com/search", params=params)
    results = response.json()

    urls = []
    if "organic_results" in results:
        for item in results["organic_results"]:
            link = item.get("link")
            if link:
                urls.append(link)
    return urls

# === Главная ===
@app.route("/")
def homepage():
    return render_template("home.html")

# === Вход ===
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # тут может быть проверка логина
        return redirect("/dashboard")
    return render_template("login.html")

# === Регистрация ===
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # тут может быть регистрация
        return redirect("/dashboard")
    return render_template("register.html")

# === Dashboard ===
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    selected_plan = None
    if request.method == "POST":
        selected_plan = request.form.get("plan")
    return render_template("dashboard.html", selected_plan=selected_plan)

# === Tarife ===
@app.route("/preise")
def preise():
    return render_template("preise.html")

# === E-Mail-Suche (ключ + локация) ===
@app.route("/emails", methods=["GET", "POST"])
def emails():
    results = []
    if request.method == "POST":
        keyword = request.form.get("keyword")
        location = request.form.get("location")
        radius_km = int(request.form.get("radius", 10))

        urls = get_maps_results(keyword, location, radius_km)
        all_emails = set()

        for url in urls:
            emails = extract_emails_from_url(url)
            all_emails.update(emails)

        email_limit = get_email_limit()
        results = list(all_emails)[:int(email_limit)]
        session["emails"] = results

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



# === Заглушка: Email-Versand ===
@app.route("/send")
def send():
    return render_template("send.html")

# === Запуск (локальный) ===
if __name__ == "__main__":
    app.run(debug=True)
