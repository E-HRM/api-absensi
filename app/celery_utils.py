from celery import Celery
from . import create_app

def make_celery(app):
    """
    Konfigurasi Celery agar berjalan di dalam konteks aplikasi Flask.
    Ini memastikan task Celery memiliki akses ke konfigurasi aplikasi,
    ekstensi, dan lain-lain.
    """
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

# Inisialisasi Celery dengan aplikasi Flask
flask_app = create_app()
celery = make_celery(flask_app)