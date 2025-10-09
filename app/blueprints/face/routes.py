from flask import Blueprint, request, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...utils.responses import ok, error
from ...services.face_service import verify_user, enroll_user_task # <-- 1. Impor task
from ...services.storage.supabase_storage import list_objects, signed_url
from ...services.notification_service import send_notification
from ...db import get_session
from ...db.models import Device, User
from ...utils.timez import now_local

face_bp = Blueprint("face", __name__)


@face_bp.post("/api/face/enroll")
def enroll():
    user_id = (request.form.get("user_id") or "").strip()
    if not user_id:
        return error("user_id wajib ada", 400)

    files = request.files.getlist("images")
    if not any(f.filename for f in files):
        return error("Kirim minimal satu file di field 'images'", 400)

    fcm_token = (request.form.get("fcm_token") or "").strip()
    if not fcm_token:
        return error("fcm_token wajib ada untuk registrasi perangkat", 400)

    try:
        # Baca file menjadi bytes untuk dikirim ke Celery
        images_data = [f.read() for f in files]
        
        # Panggil task di background
        enroll_user_task.delay(user_id, images_data)

        # Logika penyimpanan perangkat tetap di sini karena cepat
        device_label = request.form.get("device_label") or None
        platform = request.form.get("platform") or None
        os_version = request.form.get("os_version") or None
        app_version = request.form.get("app_version") or None
        device_identifier = request.form.get("device_identifier") or None
        user_name = "Karyawan"

        with get_session() as s:
            user = s.execute(
                select(User).where(User.id_user == user_id)
            ).scalar_one_or_none()
            if user is None:
                return error(f"User dengan id_user '{user_id}' tidak ditemukan.", 404)
            user_name = user.nama_pengguna

            device = None
            if device_identifier:
                device = s.execute(
                    select(Device).where(
                        Device.id_user == user_id,
                        Device.device_identifier == device_identifier
                    )
                ).scalar_one_or_none()

            now_naive_utc = now_local().replace(tzinfo=None)

            if device is None:
                device = Device(
                    id_user=user_id, device_label=device_label, platform=platform,
                    os_version=os_version, app_version=app_version,
                    device_identifier=device_identifier, last_seen=now_naive_utc,
                    fcm_token=fcm_token, fcm_token_updated_at=now_naive_utc
                )
                s.add(device)
            else:
                device.device_label = device_label or device.device_label
                device.platform = platform or device.platform
                device.os_version = os_version or device.os_version
                device.app_version = app_version or device.app_version
                device.last_seen = now_naive_utc
                device.fcm_token = fcm_token or device.fcm_token
                device.fcm_token_updated_at = now_naive_utc

            s.commit()
            s.refresh(device)
            device_id = device.id_device
        
        # NOTIFIKASI SUKSES PENDAFTARAN DIKIRIM OLEH WORKER CELERY SETELAH SELESAI
        # Kita tetap kirim notifikasi awal untuk konfirmasi
        try:
            send_notification(
                event_trigger='FACE_REGISTRATION_SUCCESS',
                user_id=user_id,
                dynamic_data={'nama_karyawan': user_name},
                session=s  # Anda mungkin perlu membuat sesi baru di sini jika di luar blok 'with'
            )
        except Exception as e:
            current_app.logger.error(f"Gagal mengirim notifikasi registrasi wajah untuk user {user_id}: {e}")

        # Beri respons cepat ke pengguna
        return ok(
            message="Proses pendaftaran wajah telah dimulai. Anda akan menerima notifikasi setelah selesai.",
            device_id=device_id
        )

    except Exception as e:
        current_app.logger.error(f"Kesalahan pada endpoint enroll: {e}", exc_info=True)
        return error(str(e), 400)

# Endpoint /verify dan /get_face_data tidak berubah
# ...
@face_bp.post("/api/face/verify")
def verify():
    # ... (kode tidak berubah)
    user_id = (request.form.get("user_id") or "").strip()
    metric = (request.form.get("metric") or "cosine").lower()
    threshold = request.form.get("threshold", type=float, default=(0.45 if metric == "cosine" else 1.4))
    f = request.files.get("image")

    if not user_id:
        return error("user_id wajib ada", 400)
    if f is None:
        return error("Field 'image' wajib ada", 400)

    try:
        data = verify_user(user_id, f, metric=metric, threshold=threshold)
        return ok(**data)
    except FileNotFoundError as e:
        return error(str(e), 404)
    except Exception as e:
        current_app.logger.error(f"Kesalahan pada endpoint verify: {e}", exc_info=True)
        return error(str(e), 400)

@face_bp.get("/api/face/<user_id>")
def get_face_data(user_id: str):
    # ... (kode tidak berubah)
    user_id = (user_id or "").strip()
    if not user_id:
        return error("user_id wajib ada", 400)

    try:
        prefix = f"face_detection/{user_id}"

        items = list_objects(prefix)
        files = []
        for item in items:
            name = item.get("name") or item.get("Name")
            if not name:
                continue

            path = f"{prefix}/{name}"
            url = signed_url(path)
            files.append({
                "name": name,
                "path": path,
                "signed_url": url
            })

        return ok(user_id=user_id, prefix=prefix, count=len(files), items=files)
    except Exception as e:
        current_app.logger.error(f"Kesalahan pada endpoint get_face_data: {e}", exc_info=True)
        return error(str(e), 400)