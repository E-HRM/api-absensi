# celery_worker.py
# Jalankan dengan:
#   celery -A celery_worker:app worker --loglevel=INFO --pool=solo
#
# Fungsi:
# - Membuat Flask app lewat create_app()
# - Mengikat Celery ke app_context (init_celery)
# - Memanggil init_face_engine() saat boot supaya InsightFace siap dipakai task

import logging

from app import create_app
from app.extensions import celery, init_celery

# 1) Buat Flask app & bind Celery ke konteks Flask
flask_app = create_app()
init_celery(flask_app)

# 2) Import modul yang berisi task agar ter-register di worker
#    (Abaikan/biarkan try-except kalau sebagian modul belum ada)
import app.services.face_service  # noqa: F401
try:
    import app.blueprints.absensi.tasks  # noqa: F401
except Exception:
    pass

# 3) Inisialisasi engine InsightFace saat worker start
#    Dengan begini, get_face_engine() tidak akan "None".
try:
    from app.extensions import init_face_engine
    with flask_app.app_context():
        init_face_engine()  # <- kunci mengatasi error "engine not initialized"
        logging.getLogger(__name__).info("[celery_worker] InsightFace engine initialized on worker boot.")
except Exception as e:
    # Jangan matikan worker; log saja untuk diagnosa.
    logging.getLogger(__name__).warning("[celery_worker] init_face_engine gagal saat startup: %s", e)

# 4) Ekspor Celery app sebagai entrypoint untuk -A celery_worker:app
app = celery
