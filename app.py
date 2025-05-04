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

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

if __name__ == "__main__":
    app.run()
