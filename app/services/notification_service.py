# flask_api_face/app/services/notification_service.py

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from firebase_admin import messaging
from sqlalchemy.orm import Session

# Coba impor initialize_firebase dari app.extensions, jika gagal, fallback ke app.firebase
try:
    from ..extensions import initialize_firebase
except (ImportError, AttributeError):
    from ..firebase import initialize_firebase


from ..db.models import NotificationTemplate, Device, Notification


def _format_message(template: str, data: Dict[str, Any]) -> str:
    """Ganti placeholder di dalam template dengan data."""
    if not template:
        return ""
    result = template
    for key, value in data.items():
        token = f"{{{key}}}"
        result = result.replace(token, str(value) if value is not None else "")
    return result


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
        pass

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
        print(f"Peringatan: Tidak ada token FCM yang valid untuk user '{user_id}'.")
        return

    title = _format_message(template.title_template, dynamic_data)
    body = _format_message(template.body_template, dynamic_data)

    # Simpan notifikasi ke database untuk riwayat in-app
    notif = Notification(
        id_user=user_id,
        title=title,
        body=body,
        data_json=json.dumps(dynamic_data) if dynamic_data else None,
        created_at=datetime.utcnow(),
    )
    session.add(notif)
    session.commit()

    # --- PERBAIKAN UTAMA DI SINI ---
    # Mengirim notifikasi sebagai 'data message' untuk memastikan pengiriman di background.
    # Klien (Android/iOS) harus di-setup untuk menangani 'data message' ini dan
    # membuat notifikasi lokal.
    message = messaging.MulticastMessage(
        tokens=tokens,
        data={
            "title": title,
            "body": body,
            # Anda bisa menambahkan data lain di sini jika diperlukan oleh klien
            # misalnya, untuk navigasi deep-link saat notifikasi dibuka.
            "notification_id": str(notif.id_notification),
            "event_trigger": event_trigger,
        },
        # Konfigurasi spesifik per platform untuk meningkatkan kemungkinan pengiriman
        android=messaging.AndroidConfig(
            priority="high",
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    content_available=True, # Membangunkan aplikasi iOS di background
                )
            )
        ),
    )
    # ---------------------------------

    try:
        response = messaging.send_multicast(message)
        print(f"Notifikasi dikirim untuk user '{user_id}': {response.success_count} sukses, {response.failure_count} gagal")
        
        # Opsi: Tangani token yang tidak valid/gagal
        if response.failure_count > 0:
            responses = response.responses
            failed_tokens = []
            for idx, resp in enumerate(responses):
                if not resp.success:
                    failed_tokens.append(tokens[idx])
            print(f"Token yang gagal: {failed_tokens}")
            # Di sini Anda bisa menambahkan logika untuk menghapus atau menonaktifkan token yang gagal dari DB

    except Exception as e:
        print(f"Gagal total mengirim notifikasi FCM untuk user '{user_id}': {e}")