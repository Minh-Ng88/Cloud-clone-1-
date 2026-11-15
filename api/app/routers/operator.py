from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ConversionJob, OutboxEvent
from app.schemas import JobList, JobStatus, OutboxOut, StatsOut, job_to_out
from app.security import Principal, require_operator
from app.services.stats import queue_stats

router = APIRouter(prefix="/operator", tags=["operator"], dependencies=[Depends(require_operator)])


@router.get("/jobs", response_model=JobList)
def list_all_jobs(status: JobStatus | None = None, owner_id: str | None = None,
                  limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    cond = []
    if status:
        cond.append(ConversionJob.status == status)
    if owner_id:
        cond.append(ConversionJob.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(ConversionJob).where(*cond)) or 0
    rows = db.execute(select(ConversionJob).where(*cond).order_by(
        ConversionJob.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return JobList(items=[job_to_out(j) for j in rows], total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    return queue_stats(db)


@router.get("/outbox", response_model=list[OutboxOut])
def outbox(published: bool = False, limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db)):
    cond = OutboxEvent.published_at.is_not(None) if published else OutboxEvent.published_at.is_(None)
    return db.execute(select(OutboxEvent).where(cond).order_by(
        OutboxEvent.created_at.desc()).limit(limit)).scalars().all()
