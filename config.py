import os

# Абсолютный путь до текущей директории
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Путь к базе данных (используем /tmp по умолчанию для Render)
DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join("/tmp", "leadgen.db"))

class Config:
    # Секретный ключ для Flask (используется для сессий, CSRF и пр.)
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "super-secret-key")

    # Строка подключения к базе данных
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"

    # Отключаем предупреждение SQLAlchemy
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Дополнительно (если планируешь отправку email)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")  # твой email
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")  # пароль приложения или SMTP
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
