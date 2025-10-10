# app/tasks/absensi_tasks.py
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from celery.utils.log import get_task_logger
from celery import states
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from celery_worker import app as celery_app
from app.db.attendance import Base, Attendance
from app.services.notification_service import (
    send_checkin_notification,
    send_checkout_notification,
)

logger = get_task_logger(__name__)
py_logger = logging.getLogger(__name__)

# --- SQLAlchemy engine/session khusus worker (independen dari Flask)
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/db_ehrm")
_engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# Opsional: pastikan tabel ada (boleh dimatikan kalau pakai migrasi Alembic)
Base.metadata.create_all(_engine)


def _upsert_attendance(
    session,
    user_id: str,
    action: str,  # "CHECKIN" | "CHECKOUT"
    ts_utc: datetime,
    location: Optional[Dict[str, Any]],
    meta: Optional[Dict[str, Any]],
):
    att = Attendance(
        user_id=user_id,
        action=action,
        timestamp_utc=ts_utc,
        latitude=location.get("lat") if location else None,
        longitude=location.get("lng") if location else None,
        raw_location=location,
        meta=meta,
        status="RECORDED",
    )
    session.add(att)
    session.flush()  # biar dapat id
    return att


@celery_app.task(
    name="process_checkin_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,  # max 5 menit
    retry_jitter=True,
    max_retries=5,
)
def process_checkin_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload:
    {
      "user_id": "...",
      "timestamp_iso": "2025-10-10T03:15:12.345Z",
      "location": {"lat": -8.65, "lng": 115.22, "accuracy": 12},
      "meta": {"source": "mobile", "device_id": "..."}
    }
    """
    logger.info("process_checkin_task START user_id=%s task_id=%s", payload.get("user_id"), self.request.id)

    session = _SessionLocal()
    try:
        user_id = payload["user_id"]
        ts_utc = datetime.fromisoformat(payload["timestamp_iso"].replace("Z", "+00:00"))
        loc = payload.get("location")
        meta = payload.get("meta")

        att = _upsert_attendance(session, user_id, "CHECKIN", ts_utc, loc, meta)
        session.commit()

        # Notifikasi
        try:
            send_checkin_notification(user_id=user_id, timestamp_utc=ts_utc, location=loc)
        except Exception as nf_err:
            # Notifikasi gagal tidak membatalkan pencatatan; cukup dicatat
            logger.warning("FCM check-in gagal user_id=%s err=%s", user_id, nf_err)

        result = {
            "status": "ok",
            "task": self.name,
            "task_id": self.request.id,
            "attendance_id": str(att.id),
        }
        logger.info("process_checkin_task DONE user_id=%s attendance_id=%s", user_id, att.id)
        return result

    except Exception as e:
        session.rollback()
        logger.exception("process_checkin_task FAILED task_id=%s err=%s", self.request.id, e)
        self.update_state(state=states.FAILURE, meta={"exc": str(e)})
        raise
    finally:
        session.close()


@celery_app.task(
    name="process_checkout_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def process_checkout_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload sama seperti check-in.
    """
    logger.info("process_checkout_task START user_id=%s task_id=%s", payload.get("user_id"), self.request.id)

    session = _SessionLocal()
    try:
        user_id = payload["user_id"]
        ts_utc = datetime.fromisoformat(payload["timestamp_iso"].replace("Z", "+00:00"))
        loc = payload.get("location")
        meta = payload.get("meta")

        att = _upsert_attendance(session, user_id, "CHECKOUT", ts_utc, loc, meta)
        session.commit()

        # Notifikasi
        try:
            send_checkout_notification(user_id=user_id, timestamp_utc=ts_utc, location=loc)
        except Exception as nf_err:
            logger.warning("FCM checkout gagal user_id=%s err=%s", user_id, nf_err)

        result = {
            "status": "ok",
            "task": self.name,
            "task_id": self.request.id,
            "attendance_id": str(att.id),
        }
        logger.info("process_checkout_task DONE user_id=%s attendance_id=%s", user_id, att.id)
        return result

    except Exception as e:
        session.rollback()
        logger.exception("process_checkout_task FAILED task_id=%s err=%s", self.request.id, e)
        self.update_state(state=states.FAILURE, meta={"exc": str(e)})
        raise
    finally:
        session.close()
