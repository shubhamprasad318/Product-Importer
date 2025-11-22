from celery import Celery
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

celery_app = Celery(
    "product_importer",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
)
