import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, request_id_var
from app.models import ConversionJob
from app.schemas import (AttemptOut, ConversionOptions, DownloadOut, JobList, JobOut, JobStatus,
                         job_to_out)
from app.security import Principal, current_principal
from app.services import jobs as svc
from app.storage import get_storage
from app.timeutil import aware, now_utc

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _parse_options(raw: str | None) -> ConversionOptions:
    if not raw:
        return ConversionOptions()
    try:
        return ConversionOptions.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ApiError(422, "INVALID_OPTIONS", "Trường options không hợp lệ", {"reason": str(e)[:500]})


@router.post("", response_model=JobOut, status_code=202)
def create_job(response: Response, file: UploadFile = File(...), options: str | None = Form(None),
               p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    opts = _parse_options(options)
    data = file.file.read(get_settings().upload_limit_bytes + 1)
    job = svc.create_job(db, get_storage(), p.user_id, file.filename, file.content_type, data,
                         opts, request_id_var.get())
    response.headers["Location"] = f"/jobs/{job.id}"
    return job_to_out(job)


@router.get("", response_model=JobList)
def list_jobs(status: JobStatus | None = None, limit: int = Query(20, ge=1, le=100),
              offset: int = Query(0, ge=0), p: Principal = Depends(current_principal),
              db: Session = Depends(get_db)):
    cond = [ConversionJob.owner_id == p.user_id]
    if status:
        cond.append(ConversionJob.status == status)
    total = db.scalar(select(func.count()).select_from(ConversionJob).where(*cond)) or 0
    rows = db.execute(select(ConversionJob).where(*cond).order_by(
        ConversionJob.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return JobList(items=[job_to_out(j) for j in rows], total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    return job_to_out(svc.get_job_for(db, job_id, p))


@router.get("/{job_id}/attempts", response_model=list[AttemptOut])
def get_attempts(job_id: uuid.UUID, p: Principal = Depends(current_principal),
                 db: Session = Depends(get_db)):
    return svc.get_job_for(db, job_id, p).attempt_log


@router.post("/{job_id}/retry", response_model=JobOut, status_code=202)
def retry(job_id: uuid.UUID, p: Principal = Depends(current_principal),
          db: Session = Depends(get_db)):
    return job_to_out(svc.retry_job(db, job_id, p))


@router.get("/{job_id}/download", response_model=DownloadOut)
def download(job_id: uuid.UUID, p: Principal = Depends(current_principal),
             db: Session = Depends(get_db)):
    s = get_settings()
    job = svc.get_job_for(db, job_id, p)
    r = job.result
    if job.status != "succeeded" or r is None:
        raise ApiError(409, "RESULT_NOT_READY", "Job chưa có PDF", {"status": job.status})
    if r.deleted_at is not None or aware(r.expires_at) <= now_utc():
        raise ApiError(410, "RESULT_EXPIRED", "PDF đã hết hạn tải về",
                       {"expired_at": aware(r.expires_at).isoformat()})
    stem = job.original_filename.rsplit(".", 1)[0] or "result"
    filename = f"{stem}.pdf"
    url = get_storage().presign_download(r.bucket, r.object_key, filename, s.download_url_ttl_seconds)
    return DownloadOut(download_url=url, url_expires_in=s.download_url_ttl_seconds,
                       result_expires_at=r.expires_at, filename=filename)
