import os
from dotenv import load_dotenv

# Загрузить .env переменные до импорта Celery
load_dotenv()

# Импорт Celery уже с настроенным брокером и задачами
from tasks import celery

if __name__ == "__main__":
    celery.start()
