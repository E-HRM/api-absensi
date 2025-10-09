from app import create_app
from app.celery_utils import make_celery

app = create_app()
celery = make_celery(app)

# Impor task Anda di sini agar worker dapat menemukannya
# Pastikan semua file yang berisi @celery.task diimpor.
from app.services.face_service import enroll_user_task