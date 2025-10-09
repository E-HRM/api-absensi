from app import create_app
from app.extensions import celery # <-- Impor dari app.extensions

app = create_app()
app.app_context().push()

# Impor task Anda di sini agar worker dapat menemukannya
from app.services.face_service import enroll_user_task