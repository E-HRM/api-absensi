# app/blueprints/absensi/tasks.py
# Task Celery untuk fitur absensi (v2 untuk menghindari bentrok signature lama)

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.extensions import celery

logger = logging.getLogger(__name__)
logger.info("[absensi.tasks] loaded from %s", __file__)


@celery.task(name="absensi.healthcheck", bind=True)
def healthcheck(self) -> Dict[str, Any]:
    host = getattr(getattr(self, "request", None), "hostname", "unknown")
    logger.info("[absensi.healthcheck] OK from %s", host)
    return {"status": "ok", "host": host}


@celery.task(name="absensi.process_checkin_task_v2", bind=True)
def process_checkin_task_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proses check-in asynchronous.
    bind=True -> argumen pertama 'self', argumen kedua 'payload' (JSON-serializable).
    """
    try:
        logger.info("[process_checkin_task_v2] start payload=%s", payload)

        # TODO: panggil service/logic checkin asli milikmu di sini.
        # from app.services.absensi_service import handle_checkin
        # res = handle_checkin(payload)
        # return {...}

        result = {
            "status": "ok",
            "message": "check-in diproses di background",
            "received_keys": list(payload.keys()),
        }

        logger.info("[process_checkin_task_v2] done user_id=%s", payload.get("user_id"))
        return result

    except Exception as e:
        logger.exception("[process_checkin_task_v2] error: %s", e)
        return {"status": "error", "message": str(e)}


@celery.task(name="absensi.process_checkout_task_v2", bind=True)
def process_checkout_task_v2(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        logger.info("[process_checkout_task_v2] start payload=%s", payload)

        # TODO: panggil service checkout milikmu
        result = {
            "status": "ok",
            "message": "checkout diproses di background",
            "received_keys": list(payload.keys()),
        }

        logger.info("[process_checkout_task_v2] done user_id=%s", payload.get("user_id"))
        return result

    except Exception as e:
        logger.exception("[process_checkout_task_v2] error: %s", e)
        return {"status": "error", "message": str(e)}


@celery.task(name="absensi.recalculate_user_day_v2", bind=True)
def recalculate_user_day_v2(self, user_id: str, tanggal: Optional[str] = None) -> Dict[str, Any]:
    try:
        logger.info("[recalculate_user_day_v2] start user_id=%s tanggal=%s", user_id, tanggal)

        # TODO: panggil service kalkulasi milikmu
        result = {
            "status": "ok",
            "message": "recalculate diproses di background",
            "user_id": user_id,
            "tanggal": tanggal,
        }

        logger.info("[recalculate_user_day_v2] done user_id=%s tanggal=%s", user_id, tanggal)
        return result

    except Exception as e:
        logger.exception("[recalculate_user_day_v2] error: %s", e)
        return {"status": "error", "message": str(e)}


# --- Alias kompatibilitas (membantu jika ada import lama di tempat lain) ---
process_checkin_task = process_checkin_task_v2
process_checkout_task = process_checkout_task_v2
recalculate_user_day = recalculate_user_day_v2
