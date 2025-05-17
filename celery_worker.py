from celery import Celery
import os

celery = Celery(
    "leadgen",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL"),
    include=["tasks"]
)
