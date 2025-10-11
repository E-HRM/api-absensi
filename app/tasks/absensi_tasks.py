# app/tasks/absensi_tasks.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from datetime import date, datetime

from app.extensions import celery
from app.db import get_session
from app.db.models import (
    Absensi,
    User,
    Location,
    AgendaKerja,
    AbsensiReportRecipient,
    Catatan,
    ShiftKerja,
    PolaKerja,
    AbsensiStatus,
    ReportStatus,
    Role,
    AtasanRole,
)
from app.services.notification_service import send_notification
from app.utils.timez import now_local, today_local_date

logger = logging.getLogger(__name__)
logger.info("[absensi.tasks] loaded from %s", __file__)

def _map_to_atasan_role(user_role: Role) -> AtasanRole | None:
    if not user_role:
        return None
    if user_role == Role.HR:
        return AtasanRole.HR
    if user_role == Role.OPERASIONAL:
        return AtasanRole.OPERASIONAL
    if user_role == Role.DIREKTUR:
        return AtasanRole.DIREKTUR
    return None

@celery.task(name="absensi.healthcheck", bind=True)
def healthcheck(self) -> Dict[str, Any]:
    host = getattr(getattr(self, "request", None), "hostname", "unknown")
    logger.info("[absensi.healthcheck] OK from %s", host)
    return {"status": "ok", "host": host}

@celery.task(name="absensi.process_checkin_task_v2", bind=True)
def process_checkin_task_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proses check-in asynchronous.
    """
    logger.info("[process_checkin_task_v2] start payload=%s", payload)
    user_id = payload.get("user_id")
    today = date.fromisoformat(payload["today_local"])
    now_dt = datetime.fromisoformat(payload["now_local_iso"]).replace(tzinfo=None)
    location = payload.get("location", {})
    
    with get_session() as s:
        try:
            # 1. Tentukan status kehadiran (tepat waktu / terlambat)
            jadwal_kerja = s.query(ShiftKerja).join(PolaKerja).filter(
                ShiftKerja.id_user == user_id,
                ShiftKerja.tanggal_mulai <= today,
                ShiftKerja.tanggal_selesai >= today,
            ).first()

            status_kehadiran = AbsensiStatus.tepat
            if jadwal_kerja and jadwal_kerja.polaKerja and jadwal_kerja.polaKerja.jam_mulai:
                jam_masuk_seharusnya = jadwal_kerja.polaKerja.jam_mulai.time()
                jam_checkin_aktual = now_dt.time()
                if jam_checkin_aktual > jam_masuk_seharusnya:
                    status_kehadiran = AbsensiStatus.terlambat

            # 2. Buat record absensi baru
            rec = Absensi(
                id_user=user_id,
                tanggal=today,
                jam_masuk=now_dt,
                status_masuk=status_kehadiran,
                id_lokasi_datang=location.get("id"),
                in_latitude=location.get("lat"),
                in_longitude=location.get("lng"),
                face_verified_masuk=True,
                face_verified_pulang=False, # Default
            )
            s.add(rec)
            s.flush() # flush() untuk mendapatkan id_absensi sebelum commit
            
            absensi_id = rec.id_absensi
            logger.info(f"Absensi record created with id: {absensi_id}")

            # 3. Tautkan Agenda Kerja
            agenda_ids = payload.get("agenda_ids", [])
            if agenda_ids:
                s.query(AgendaKerja).filter(
                    AgendaKerja.id_user == user_id,
                    AgendaKerja.id_agenda_kerja.in_(agenda_ids),
                    AgendaKerja.id_absensi.is_(None)
                ).update({"id_absensi": absensi_id}, synchronize_session=False)

            # 4. Tambahkan Catatan
            for entry in payload.get("catatan_entries", []):
                s.add(Catatan(id_absensi=absensi_id, **entry))

            # 5. Tambahkan Penerima Laporan (Recipients)
            recipient_ids = payload.get("recipients", [])
            if recipient_ids:
                recipients = s.query(User).filter(User.id_user.in_(recipient_ids)).all()
                for u in recipients:
                    s.add(AbsensiReportRecipient(
                        id_absensi=absensi_id,
                        id_user=u.id_user,
                        recipient_nama_snapshot=u.nama_pengguna,
                        recipient_role_snapshot=_map_to_atasan_role(u.role),
                        status=ReportStatus.terkirim,
                    ))

            s.commit()
            logger.info(f"[process_checkin_task_v2] SUCCESS for user_id={user_id}")

            return {"status": "ok", "message": "Check-in berhasil disimpan", "absensi_id": absensi_id}

        except Exception as e:
            s.rollback()
            logger.exception("[process_checkin_task_v2] error: %s", e)
            return {"status": "error", "message": str(e)}


@celery.task(name="absensi.process_checkout_task_v2", bind=True)
def process_checkout_task_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    # (Pastikan task checkout Anda juga memiliki logika yang benar)
    logger.info("[process_checkout_task_v2] start payload=%s", payload)
    # ... Logika untuk checkout ...
    return {"status": "ok", "message": "checkout diproses di background"}

# --- Alias kompatibilitas ---
process_checkin_task = process_checkin_task_v2
process_checkout_task = process_checkout_task_v2