from flask import Flask, render_template, request, redirect, send_file, session
from io import BytesIO
import openpyxl
import requests
import re
from bs4 import BeautifulSoup

app = Flask(__name__)

app.secret_key = "supersecretkey"

# === SerpAPI API-Key ===
SERPAPI_KEY = "435924c0a06fc34cdaed22032ba6646be2d0db381a7cfff645593d77a7bd3dcd"

# === Email-поиск по URL ===
def extract_emails_from_url(url):
    try:
        html = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"}).text
        return re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
    except:
        return []

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
        query = f"{keyword} {location}"

        urls = get_google_results(query)
        all_emails = set()

        for url in urls:
            emails = extract_emails_from_url(url)
            all_emails.update(emails)

        results = list(all_emails)
        session["emails"] = results  # ← сохраняем для экспорта

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
