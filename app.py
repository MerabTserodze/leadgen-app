
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def homepage():
    return render_template("home.html")

@app.route("/login")
def login():
    return "<h2>Login Seite (bald mit Formular)</h2>"

@app.route("/register")
def register():
    return "<h2>Registrierungsseite (bald verfügbar)</h2>"
@app.route("/preise")
def preise():
    return render_template("preise.html")



if __name__ == "__main__":
    app.run()
