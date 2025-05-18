import os
from dotenv import load_dotenv

# Загрузить переменные окружения
load_dotenv()

from tasks import celery

if __name__ == "__main__":
    celery.start()
