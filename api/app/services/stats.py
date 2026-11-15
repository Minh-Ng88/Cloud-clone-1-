from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import QUEUED, RUNNING, SUCCEEDED, FAILED, ConversionJob, OutboxEvent
from app.timeutil import aware, now_utc


def queue_stats(db: Session) -> dict:
    now = now_utc()
    counts = dict(db.execute(select(ConversionJob.status, func.count()).group_by(
        ConversionJob.status)).all())
    oldest_q = db.scalar(select(func.min(ConversionJob.created_at)).where(
        ConversionJob.status == QUEUED))
    expired = db.scalar(select(func.count()).where(
        ConversionJob.status == RUNNING, ConversionJob.lease_expires_at < now))
    pend = db.scalar(select(func.count()).where(OutboxEvent.published_at.is_(None)))
    oldest_o = db.scalar(select(func.min(OutboxEvent.created_at)).where(
        OutboxEvent.published_at.is_(None)))
    return {
        "jobs_by_status": {k: counts.get(k, 0) for k in (QUEUED, RUNNING, SUCCEEDED, FAILED)},
        "oldest_queued_age_seconds": (now - aware(oldest_q)).total_seconds() if oldest_q else None,
        "running_with_expired_lease": expired or 0,
        "pending_outbox_events": pend or 0,
        "oldest_pending_outbox_age_seconds": (now - aware(oldest_o)).total_seconds() if oldest_o else None,
    }
