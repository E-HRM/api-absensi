# flask_api_face/app/extensions.py

from __future__ import annotations

import os
import json
from typing import Optional
import logging
from insightface.app import FaceAnalysis

from flask import Flask, current_app
from flask_cors import CORS
from celery import Celery, Task

from supabase import create_client, Client
import firebase_admin
from firebase_admin import credentials

# --- Windows + multiprocessing quirk ---
if os.name == "nt":
    os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")

# --- Globals ---
celery: Celery = Celery(__name__)
_face_engine: Optional[FaceAnalysis] = None # <-- Kita hanya akan pakai variabel ini
_supabase: Optional[Client] = None
_firebase_app: Optional[firebase_admin.App] = None
log = logging.getLogger(__name__)

# -------------------------
# Celery <-> Flask binding
# -------------------------
class FlaskContextTask(Task):
    """
    Memastikan setiap task berjalan di dalam Flask app_context.
    Gunakan atribut 'flask_app' agar tidak bentrok dengan Task.app (Celery app).
    """
    flask_app: Optional[Flask] = None

    def __call__(self, *args, **kwargs):
        app_obj = getattr(self, "flask_app", None)
        if app_obj is None:
            try:
                app_obj = current_app._get_current_object()
            except Exception:
                app_obj = None

        if app_obj is not None:
            with app_obj.app_context():
                return self.run(*args, **kwargs)
        return self.run(*args, **kwargs)


def init_celery(app: Flask) -> None:
    """Konfigurasi Celery dan pasang Task base yang membawa app_context Flask."""
    broker = app.config.get("CELERY_BROKER_URL")
    backend = app.config.get("CELERY_RESULT_BACKEND")

    celery.conf.update(
        broker_url=broker,
        result_backend=backend,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone=app.config.get("TIMEZONE", "UTC"),
        enable_utc=False,
    )

    celery.Task = FlaskContextTask
    FlaskContextTask.flask_app = app


# -------------------------
# Face engine (insightface)
# -------------------------
def init_face_engine(app=None):
    """
    Inisialisasi global face_engine sekali saja.
    Argumen 'app' opsional agar kompatibel dengan pemanggilan lama/baru.
    """
    global _face_engine  # <-- DIUBAH: Menggunakan _face_engine
    if _face_engine is not None:
        return _face_engine

    try:
        providers = ["CPUExecutionProvider"]
        model_name = "buffalo_l"
        det_size = (640, 640)

        engine = FaceAnalysis(name=model_name, providers=providers)
        engine.prepare(ctx_id=0, det_size=det_size)

        _face_engine = engine  # <-- DIUBAH: Menyimpan ke _face_engine
        log.info("InsightFace initialized: name=%s providers=%s", model_name, providers)
        return _face_engine
    except Exception as e:
        log.warning("InsightFace init failed: %s", e)
        return None

def get_face_engine() -> FaceAnalysis:
    """Lazy getter: kalau belum ada, coba init dari current_app."""
    global _face_engine
    if _face_engine is None:
        try:
            app = current_app._get_current_object()
        except Exception:
            app = None

        if app is not None:
            init_face_engine(app)

    if _face_engine is None:
        raise RuntimeError("Face recognition engine not initialized. "
                           "Pastikan worker Celery memanggil init_face_engine() "
                           "atau jalankan task dalam konteks Flask dengan init_celery().")
    return _face_engine


# -------------------------
# Supabase
# -------------------------
def init_supabase(app: Flask) -> None:
    global _supabase
    if _supabase is not None:
        return

    url = app.config.get("SUPABASE_URL")
    key = app.config.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        app.logger.warning("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY tidak di-set.")
        return

    try:
        _supabase = create_client(url, key)
        app.logger.info("Supabase client initialized.")
    except Exception as e:
        _supabase = None
        app.logger.error(f"Gagal inisialisasi Supabase: {e}", exc_info=True)


def get_supabase() -> Optional[Client]:
    return _supabase


# -------------------------
# Firebase Admin
# -------------------------
def init_firebase(app: Flask) -> None:
    """Inisialisasi Firebase Admin dari path JSON atau env JSON."""
    global _firebase_app
    if _firebase_app is not None:
        return

    cred = None
    creds_path = app.config.get("FIREBASE_CREDENTIALS_PATH")
    creds_json_str = app.config.get("FIREBASE_SERVICE_ACCOUNT_JSON")

    if creds_path and os.path.exists(creds_path):
        try:
            cred = credentials.Certificate(creds_path)
            app.logger.info(f"Loading Firebase credentials from path: {creds_path}")
        except Exception as e:
            app.logger.warning(f"Failed to load Firebase credentials from path {creds_path}: {e}")

    if cred is None and creds_json_str:
        try:
            if creds_json_str.strip().startswith("{"):
                cred_dict = json.loads(creds_json_str)
                cred = credentials.Certificate(cred_dict)
                app.logger.info("Loading Firebase credentials from FIREBASE_SERVICE_ACCOUNT_JSON.")
            else:
                app.logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON bukan JSON valid.")
        except Exception as e:
            app.logger.warning(f"Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON: {e}")

    if cred:
        try:
            _firebase_app = firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized.")
        except Exception as e:
            _firebase_app = None
            app.logger.error(f"Error initializing Firebase Admin SDK: {e}", exc_info=True)
    else:
        app.logger.warning("No valid Firebase credentials found; Firebase not initialized.")


# -------------------------
# Flask app wiring
# -------------------------
def init_app(app: Flask) -> None:
    """Dipanggil dari create_app()."""
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    init_celery(app)
    init_supabase(app)
    try:
        init_firebase(app)
    except Exception:
        app.logger.exception("Firebase init failed during app init.")