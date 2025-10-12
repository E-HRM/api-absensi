# flask_api_face/app/services/notification_service.py

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from firebase_admin import messaging
from sqlalchemy.orm import Session

# Coba impor initialize_firebase dari app.extensions, jika gagal, fallback ke app.firebase
try:
    from ..extensions import initialize_firebase  # type: ignore
except (ImportError, AttributeError):
    from ..firebase import initialize_firebase  # type: ignore

from ..db.models import NotificationTemplate, Device, Notification


def _format_message(template: str, data: Dict[str, Any]) -> str:
    """Ganti placeholder di dalam template dengan data."""
    if not template:
        return ""
    try:
        return template.format(**data)
    except Exception:
        # Supaya tidak gagal total kalau ada placeholder yang belum tersedia
        return template


def _send_multicast_compat(message: messaging.MulticastMessage, tokens: List[str]):
    """
    Kirim multicast dengan kompatibilitas lintas versi firebase_admin.
    Mengembalikan objek beratribut:
      - success_count
      - failure_count
      - responses (list dengan elemen yang punya .success: bool)
    """
    # 1) Versi baru: send_multicast (paling simpel)
    if hasattr(messaging, "send_multicast"):
        return messaging.send_multicast(message)  # type: ignore[attr-defined]

    # 2) Alternatif: send_each_for_multicast (ada di beberapa versi)
    if hasattr(messaging, "send_each_for_multicast"):
        resp = messaging.send_each_for_multicast(message)  # type: ignore[attr-defined]
        # Normalisasi struktur agar mirip dengan response send_multicast
        success = sum(1 for r in resp.responses if r.success)
        failure = len(resp.responses) - success
        # Kembalikan objek sederhana dengan atribut yang dibutuhkan
        class _Compat:
            def __init__(self, success_count, failure_count, responses):
                self.success_count = success_count
                self.failure_count = failure_count
                self.responses = responses
        return _Compat(success, failure, resp.responses)

    # 3) Versi lama: tidak ada multicast sama sekali -> gunakan send_all bila ada
    common_kwargs = dict(
        notification=message.notification,
        data=message.data,
        android=message.android,
        apns=message.apns,
        webpush=getattr(message, "webpush", None),
        fcm_options=getattr(message, "fcm_options", None),
    )
    messages = [messaging.Message(token=t, **common_kwargs) for t in tokens]

    if hasattr(messaging, "send_all"):
        resp = messaging.send_all(messages)  # type: ignore[attr-defined]
        # Struktur resp sudah punya .success_count, .failure_count, .responses
        class _Compat:
            def __init__(self, success_count, failure_count, responses):
                self.success_count = success_count
                self.failure_count = failure_count
                self.responses = responses
        return _Compat(resp.success_count, resp.failure_count, resp.responses)

    # 4) Fallback terakhir: kirim satu per satu
    responses = []
    success = 0
    for msg in messages:
        try:
            messaging.send(msg)
            class _R:
                success = True
            responses.append(_R())
            success += 1
        except Exception:
            class _R:
                success = False
            responses.append(_R())
    class _Compat:
        def __init__(self, success_count, failure_count, responses):
            self.success_count = success_count
            self.failure_count = failure_count
            self.responses = responses
    return _Compat(success, len(messages) - success, responses)


def send_notification(event_trigger: str, user_id: str, dynamic_data: Dict[str, Any], session: Session) -> None:
    """
    Kirim notifikasi push untuk pengguna tertentu.
    """
    try:
        # Pastikan Firebase diinisialisasi sebelum digunakan
        initialize_firebase()
    except Exception as e:
        print(f"Peringatan: Gagal menginisialisasi Firebase saat mengirim notifikasi: {e}")
        # Tetap lanjutkan untuk menyimpan notifikasi ke DB, tapi pengiriman push mungkin gagal

    template: NotificationTemplate | None = (
        session.query(NotificationTemplate)
        .filter(
            NotificationTemplate.event_trigger == event_trigger,
            NotificationTemplate.is_active.is_(True),
        )
        .one_or_none()
    )
    if not template:
        print(f"Peringatan: Template notifikasi untuk event '{event_trigger}' tidak ditemukan atau tidak aktif.")
        return

    devices = (
        session.query(Device)
        .filter(
            Device.id_user == user_id,
            Device.fcm_token.isnot(None),
            Device.push_enabled.is_(True),
        )
        .all()
    )
    tokens = [d.fcm_token for d in devices if d.fcm_token]
    if not tokens:
        print(f"Peringatan: Tidak ada device/token FCM aktif untuk user '{user_id}'.")
        return

    # Buat judul & body dengan placeholder yang digantikan
    title = _format_message(template.title_template or "", dynamic_data)
    body = _format_message(template.body_template or "", dynamic_data)

    # Simpan record notifikasi ke DB terlebih dahulu
    notif = Notification(
        id_user=user_id,
        event_trigger=event_trigger,
        title=title,
        body=body,
        data_json=json.dumps(dynamic_data, default=str),
        created_at=datetime.utcnow(),
    )
    session.add(notif)
    session.flush()  # supaya dapat id

    # Siapkan payload untuk FCM
    notification = messaging.Notification(title=title, body=body)
    data_payload = {
        "event_trigger": event_trigger,
        "notification_id": str(notif.id_notification),
        # Tambahkan dynamic_data supaya aplikasi bisa menampilkan detail
        "meta": json.dumps(dynamic_data, default=str),
    }

    multicast = messaging.MulticastMessage(
        tokens=tokens,
        notification=notification,
        data=data_payload,
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(content_available=True)
            )
        ),
    )

    # Kirim dengan fungsi kompatibel lintas versi
    try:
        response = _send_multicast_compat(multicast, tokens)
        print(
            f"Notifikasi dikirim untuk user '{user_id}': "
            f"{response.success_count} sukses, {response.failure_count} gagal"
        )
        # Opsi: tangani token gagal
        if response.failure_count:
            failed_tokens = []
            for idx, resp in enumerate(response.responses):
                if not getattr(resp, "success", False):
                    failed_tokens.append(tokens[idx])
            if failed_tokens:
                print(f"Token yang gagal: {failed_tokens}")
                # TODO: Anda bisa menonaktifkan/menghapus token-token ini dari DB
    except Exception as e:
        print(f"Gagal total mengirim notifikasi FCM untuk user '{user_id}': {e}")

    # Commit perubahan DB (record notifikasi)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Peringatan: Gagal commit notifikasi ke DB untuk user '{user_id}': {e}")
