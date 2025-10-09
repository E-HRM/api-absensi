# flask_api_face/celery_worker.py

from celery.signals import worker_process_init

from app import create_app
from app.extensions import celery, init_face_engine, init_supabase, init_firebase, FlaskContextTask

# Buat instance Flask untuk memberi context kepada task
flask_app = create_app()

# Pastikan Task base tahu Flask app yang benar (hindari bentrok dengan Celery app)
FlaskContextTask.flask_app = flask_app  # <- kunci agar tidak pakai Celery app

@worker_process_init.connect
def _init_each_process(**kwargs):
    """
    Dipanggil SETIAP proses worker Celery dibuat (termasuk pool workers).
    """
    with flask_app.app_context():
        print("Menginisialisasi dependency di proses worker...")
        init_supabase(flask_app)
        init_firebase(flask_app)
        init_face_engine(flask_app)
        print("Selesai inisialisasi dependency di proses worker.")

# Ekspos 'app' agar 'celery -A celery_worker:app worker ...' bisa menemukan Celery instance
app = celery
