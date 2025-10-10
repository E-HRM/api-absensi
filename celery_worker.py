# celery_worker.py
import os
from celery import Celery

def make_celery() -> Celery:
    broker = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend = os.getenv("CELERY_RESULT_BACKEND", broker)
    timezone = os.getenv("TIMEZONE", "Asia/Makassar")

    app = Celery(
        "face_rec_bg",
        broker=broker,
        backend=backend,
        include=["app.tasks.absensi_tasks"],  # pastikan modul task terdaftar
    )
    app.conf.update(
        task_track_started=True,
        timezone=timezone,
        enable_utc=False,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,           # aman bila worker crash
        worker_prefetch_multiplier=1,  # hindari penumpukan job di 1 worker
    )
    return app

# Celery instance yg dipakai oleh `celery -A celery_worker:app worker`
app = make_celery()

if __name__ == "__main__":
    app.start()
