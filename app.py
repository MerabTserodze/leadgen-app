from flask import Flask, render_template, request, redirect

app = Flask(__name__)

@app.route("/")
def homepage():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Обработка логина
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/preise")
def preise():
    return render_template("preise.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Пример: email = request.form["email"]
        return redirect("/dashboard")
    return render_template("register.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    selected_plan = None
    if request.method == "POST":
        selected_plan = request.form.get("plan")
        # Здесь ты можешь сохранить выбор в сессию, БД и т.д.
    return render_template("dashboard.html", selected_plan=selected_plan)

@app.route("/emails", methods=["GET", "POST"])
def emails():
    results = []
    if request.method == "POST":
        keyword = request.form.get("keyword")
        location = request.form.get("location")

        # Пример сгенерированных "лидов"
        results = [
            f"{keyword} Berlin – kontakt@{keyword.lower()}-{location.lower()}.de",
            f"{keyword} Experts {location} – info@{keyword.lower()}experts-{location.lower()}.com",
            f"{keyword} & Partner ({location}) – mail@partner-{keyword.lower()}.de"
        ]
    return render_template("emails.html", results=results)
    
@app.route("/send")
def send():
    return render_template("send.html")




if __name__ == "__main__":
    app.run()
