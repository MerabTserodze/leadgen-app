
from flask import Flask, render_template

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


@app.route("/register")
def register():
    return "<h2>Registrierungsseite (bald verfügbar)</h2>"
@app.route("/preise")
def preise():
    return render_template("preise.html")
    
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Обработка формы: email = request.form["email"], и т.д.
        return redirect("/dashboard")
    return render_template("register.html")



if __name__ == "__main__":
    app.run()
