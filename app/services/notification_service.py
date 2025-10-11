# flask_api_face/app/services/notification_service.py

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from firebase_admin import messaging
from ..firebase import initialize_firebase
from sqlalchemy.orm import Session

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
        initialize_firebase()
    except Exception:
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
        return

    title = _format_message(template.title_template, dynamic_data)
    body = _format_message(template.body_template, dynamic_data)

    # Simpan notifikasi ke database (ini tidak berubah)
    notif = Notification(
        id_user=user_id,
        title=title,
        body=body,
        data_json=json.dumps(dynamic_data) if dynamic_data else None,
        created_at=datetime.utcnow(),
    )
    session.add(notif)
    session.commit()

    # --- PERUBAHAN UTAMA DI SINI ---
    # Kita membuat payload yang strukturnya sama persis dengan backend Next.js.
    # Hanya ada 'notification', 'android', dan 'apns' di level atas.
    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        android=messaging.AndroidConfig(
            notification=messaging.AndroidNotification(sound="default")
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default")
            )
        ),
        # Pastikan tidak ada payload 'data' di sini
    )
    # ---------------------------------

    try:
        responses = messaging.send_each_for_multicast(message)
        success_count = sum(1 for r in responses if r.success)
        failure_count = len(responses) - success_count
        print(f"Notifikasi dikirim: {success_count} sukses, {failure_count} gagal")
    except Exception as e:
        print(f"Gagal mengirim notifikasi FCM: {e}")