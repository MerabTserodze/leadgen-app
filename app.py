from flask import Flask, render_template, request, redirect, send_file, session
from io import BytesIO
import dns.resolver
import openpyxl
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
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
    headers = {"User-Agent": "Mozilla/5.0"}
    visited = set()
    collected_emails = set()

    try:
        response = requests.get(base_url, timeout=5, headers=headers)
        if response.status_code != 200:
            return []

        html = response.text
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
        collected_emails.update(emails)
        visited.add(base_url)

        soup = BeautifulSoup(html, "html.parser")
        internal_links = []

        # Собираем до 3 внутренних ссылок
        for a in soup.find_all("a", href=True):
            href = a['href']
            if href.startswith("/") or base_url in href:
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
                clean_url = parsed.scheme + "://" + parsed.netloc + parsed.path
                if clean_url not in visited and len(internal_links) < 3:
                    internal_links.append(clean_url)

        # Пытаемся спарсить каждую внутреннюю ссылку
        for link in internal_links:
            try:
                sub_response = requests.get(link, timeout=5, headers=headers)
                if sub_response.status_code == 200:
                    sub_html = sub_response.text
                    sub_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", sub_html)
                    collected_emails.update(sub_emails)
                    visited.add(link)
            except requests.RequestException:
                continue

    except Exception as e:
        print("❌ Fehler beim Parsen:", e)

    return list(collected_emails)
EXCLUDE_DOMAINS = [
    "sentry.io", "wixpress.com", "cloudflare", "example.com",
    "no-reply", "noreply", "localhost", "wordpress.com"
]

def is_valid_email(email):
    email = email.lower()

    for d in EXCLUDE_DOMAINS:
        if d in email:
            return False

    domain = email.split("@")[-1]
    return has_mx_record(domain)

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
        "num": 30,  # до 30 результатов
        "radius": radius_km * 1000  # в метрах
    }

    try:
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()
        results = data.get("local_results", [])

        urls = []
        for place in results:
            link = place.get("website")
            if link:
                urls.append(link)

        return urls

    except Exception as e:
        print("❌ Fehler bei get_maps_results:", e)
        return []



# === Получение сайтов из Google через SerpAPI ===
def get_google_results(keyword, location):
    query = f"{keyword} {location} kontakt email"

    params = {
        "engine": "google",
        "q": query,
        "location": location,
        "hl": "de",                        # Язык результатов: немецкий
        "gl": "de",                        # Гео: Германия
        "google_domain": "google.de",     # Используем google.de
        "api_key": SERPAPI_KEY,
        "num": 20                          # Можно увеличить до 30–50
    }

    try:
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()

        urls = []
        for result in data.get("organic_results", []):
            link = result.get("link", "")
            # Убираем явный мусор
            if any(x in link for x in ["facebook.com", "youtube.com", "tripadvisor.com"]):
                continue
            urls.append(link)

        return urls

    except Exception as e:
        print("❌ Fehler bei get_google_results:", e)
        return []

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
            valid_emails = [e for e in emails if is_valid_email(e)]
            all_emails.update(valid_emails)

        # ❗️Эта строка должна иметь тот же отступ, что и весь блок
        results = list(all_emails)

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
