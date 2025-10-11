# app/blueprints/absensi/tasks.py
# Task Celery untuk fitur absensi.
# Pastikan modul ini ter-import saat worker start (lihat catatan di bawah).

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.extensions import celery

logger = logging.getLogger(__name__)


@celery.task(name="absensi.healthcheck", bind=True)
def healthcheck(self) -> Dict[str, Any]:
    """
    Task sederhana untuk cek hidup-mati worker.
    """
    host = getattr(getattr(self, "request", None), "hostname", "unknown")
    logger.info("[absensi.healthcheck] OK from %s", host)
    return {"status": "ok", "host": host}


@celery.task(name="absensi.process_checkin_task", bind=True)
def process_checkin_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proses check-in secara asynchronous.
    NOTE:
      - Karena bind=True, argumen pertama WAJIB 'self'.
      - 'payload' harus JSON-serializable (dict of str/number/bool/list/dict).
    """
    try:
        logger.info("[process_checkin_task] start payload=%s", payload)

        # TODO: Panggil service/logic milikmu di sini.
        # Misal:
        #   from app.services.absensi_service import handle_checkin
        #   result = handle_checkin(payload)
        # Untuk sementara, kita kembalikan ack minimal:
        result = {
            "status": "ok",
            "message": "check-in diproses di background",
            "received_keys": list(payload.keys()),
        }

        logger.info("[process_checkin_task] done user_id=%s", payload.get("user_id"))
        return result

    except Exception as e:
        logger.exception("[process_checkin_task] error: %s", e)
        return {"status": "error", "message": str(e)}


@celery.task(name="absensi.process_checkout_task", bind=True)
def process_checkout_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proses checkout secara asynchronous.
    """
    try:
        logger.info("[process_checkout_task] start payload=%s", payload)

        # TODO: panggil service checkout milikmu
        result = {
            "status": "ok",
            "message": "checkout diproses di background",
            "received_keys": list(payload.keys()),
        }

        logger.info("[process_checkout_task] done user_id=%s", payload.get("user_id"))
        return result

    except Exception as e:
        logger.exception("[process_checkout_task] error: %s", e)
        return {"status": "error", "message": str(e)}


@celery.task(name="absensi.recalculate_user_day", bind=True)
def recalculate_user_day(self, user_id: str, tanggal: Optional[str] = None) -> Dict[str, Any]:
    """
    Recalculate rekap harian user (misal setelah koreksi manual).
    'tanggal' opsional (format 'YYYY-MM-DD'); bila None, gunakan hari ini (di service).
    """
    try:
        logger.info("[recalculate_user_day] start user_id=%s tanggal=%s", user_id, tanggal)

        # TODO: panggil service kalkulasi milikmu
        result = {
            "status": "ok",
            "message": "recalculate diproses di background",
            "user_id": user_id,
            "tanggal": tanggal,
        }

        logger.info("[recalculate_user_day] done user_id=%s tanggal=%s", user_id, tanggal)
        return result

    except Exception as e:
        logger.exception("[recalculate_user_day] error: %s", e)
        return {"status": "error", "message": str(e)}
