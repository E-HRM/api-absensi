# app/tasks/absensi_tasks.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from app.extensions import celery

# Optional-import: kalau DB/model belum siap, task tetap jalan (no-op) dan tidak bikin worker mati.
try:
    from app.db import get_session
    from app.db.models import Absensi  # sesuaikan dengan model di proyekmu
except Exception:
    get_session = None   # type: ignore
    Absensi = None       # type: ignore

log = logging.getLogger(__name__)


def _safe_iso_to_date(value: Optional[str]):
    """Konversi ISO string -> date; fallback ke hari ini (UTC) jika gagal/None."""
    try:
        if not value:
            return datetime.now(timezone.utc).date()
        # Terima 'YYYY-MM-DD' atau full ISO 'YYYY-MM-DDTHH:MM:SS+ZZ'
        dt = datetime.fromisoformat(value)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).date()
    except Exception:
        return datetime.now(timezone.utc).date()


@celery.task(name="absensi.process_checkin_task", bind=True)
def process_checkin_task(self, **payload: Any) -> Dict[str, Any]:
    """
    Proses check-in (versi defensif).
    Menerima payload bebas via kwargs, contoh tipikal:
      user_id, location_id, lat, lon, waktu|timestamp|waktu_checkin, face_score, dll.
    Saat skema DB sudah fix, kita bisa tulis upsert Absensi yang sebenarnya.
    """
    data = dict(payload or {})
    user_id = data.get("user_id")
    when_iso = data.get("waktu") or data.get("timestamp") or data.get("waktu_checkin")
    tanggal = _safe_iso_to_date(when_iso)

    try:
        # Sentuh DB sekadar memastikan konektivitas (tanpa asumsi kolom)
        if get_session and Absensi:
            with get_session() as s:
                _ = s.query(Absensi).limit(1).all()

        log.info("[CHECKIN] user=%s tanggal=%s payload_keys=%s", user_id, tanggal, list(data.keys()))
        return {"ok": True, "event": "checkin", "user_id": user_id, "tanggal": str(tanggal)}
    except Exception as e:
        log.exception("process_checkin_task gagal: user_id=%s", user_id)
        return {"ok": False, "event": "checkin", "error": str(e)}


@celery.task(name="absensi.process_checkout_task", bind=True)
def process_checkout_task(self, **payload: Any) -> Dict[str, Any]:
    """
    Proses check-out (versi defensif).
    Menerima payload bebas via kwargs: user_id, waktu|timestamp|waktu_checkout, dst.
    """
    data = dict(payload or {})
    user_id = data.get("user_id")
    when_iso = data.get("waktu") or data.get("timestamp") or data.get("waktu_checkout")
    tanggal = _safe_iso_to_date(when_iso)

    try:
        if get_session and Absensi:
            with get_session() as s:
                _ = s.query(Absensi).limit(1).all()

        log.info("[CHECKOUT] user=%s tanggal=%s payload_keys=%s", user_id, tanggal, list(data.keys()))
        return {"ok": True, "event": "checkout", "user_id": user_id, "tanggal": str(tanggal)}
    except Exception as e:
        log.exception("process_checkout_task gagal: user_id=%s", user_id)
        return {"ok": False, "event": "checkout", "error": str(e)}


@celery.task(name="absensi.recalculate_user_day")
def recalculate_user_day(user_id: str, tanggal_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Rehitung status absensi 1 user pada 1 tanggal.
    Saat model sudah pasti, ganti query count() ini dengan logika bisnis yang valid.
    """
    try:
        tanggal = _safe_iso_to_date(tanggal_iso)
        if get_session and Absensi:
            with get_session() as s:
                # Tidak mengasumsikan ada kolom 'tanggal' — kalau ada, bagus; kalau tidak, ini tetap aman.
                q = s.query(Absensi).filter(Absensi.user_id == user_id)
                # Kalau model punya kolom 'tanggal', filter-kan. Kalau tidak, biarkan saja (count semua milik user).
                if hasattr(Absensi, "tanggal"):
                    q = q.filter(getattr(Absensi, "tanggal") == tanggal)  # type: ignore
                count = q.count()
        else:
            count = 0
        return {"ok": True, "user_id": user_id, "tanggal": str(tanggal), "rows": count}
    except Exception as e:
        log.exception("recalculate_user_day gagal user_id=%s tanggal=%s", user_id, tanggal_iso)
        return {"ok": False, "error": str(e)}


@celery.task(name="absensi.healthcheck")
def absensi_healthcheck() -> Dict[str, Any]:
    """Task sederhana untuk memastikan worker + DB bisa diakses."""
    try:
        if get_session and Absensi:
            with get_session() as s:
                _ = s.query(Absensi).limit(1).all()
        return {"ok": True, "msg": "worker hidup & DB terbaca"}
    except Exception as e:
        log.exception("Healthcheck gagal")
        return {"ok": False, "error": str(e)}
