"""Worker giả lập: cài đặt THAM CHIẾU giao thức DB trong docs/contract.md (§3).

Dùng cho test và smoke test. Worker thật làm tương đương bằng SQL trực tiếp trên PostgreSQL
(lease, attempts, trạng thái) và không cần import gì từ API.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

LEASE_SECONDS = 60
BACKOFF_SECONDS = 5
RESULT_TTL_HOURS = 24
RESULTS_BUCKET = os.getenv("S3_BUCKET_RESULTS", "results")


def result_key(job_id, attempt_no: int) -> str:
    return f"jobs/{job_id}/attempt-{attempt_no}.pdf"


def _enqueue(c, job_id, delay_seconds: float = 0) -> None:
    """Ghi sự kiện outbox cho relay (cùng giao dịch với thay đổi trạng thái job)."""
    mid = str(uuid.uuid4())
    c.execute(text("""
        INSERT INTO outbox_events (id, aggregate_id, event_type, payload, created_at, available_at)
        SELECT CAST(:mid AS uuid), j.id, 'job.convert.requested',
               jsonb_build_object('schema_version', 1, 'message_id', CAST(:mid AS text),
                                  'type', 'job.convert.requested', 'job_id', CAST(j.id AS text),
                                  'source_key', s.object_key, 'format', j.source_format,
                                  'request_id', j.request_id, 'enqueued_at', now()),
               now(), now() + make_interval(secs => CAST(:d AS double precision))
        FROM conversion_jobs j JOIN source_objects s ON s.job_id = j.id
        WHERE j.id = CAST(:j AS uuid)"""), {"mid": mid, "j": str(job_id), "d": delay_seconds})


def _expire(c, job_id, enqueue: bool = True) -> str:
    """Lease đã hết hạn: đóng attempt đang chạy, đưa job về queued (còn lượt) hoặc failed."""
    c.execute(text("""UPDATE conversion_attempts SET outcome = 'lease_expired', finished_at = now(),
                      error_code = 'LEASE_EXPIRED', error_message = 'Worker không gia hạn lease'
                      WHERE job_id = CAST(:j AS uuid) AND outcome = 'running'"""), {"j": str(job_id)})
    status = c.execute(text("""
        UPDATE conversion_jobs SET
          status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
          finished_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END,
          worker_id = NULL, lease_expires_at = NULL, error_code = 'LEASE_EXPIRED',
          error_message = 'Worker không gia hạn lease đúng hạn', updated_at = now()
        WHERE id = CAST(:j AS uuid) RETURNING status"""), {"j": str(job_id)}).scalar_one()
    if status == "queued" and enqueue:
        _enqueue(c, job_id)
    return status


def claim(job_id, worker_id: str, message_id=None, lease_seconds: int = LEASE_SECONDS):
    """Nhận job. Trả dict thông tin nếu nhận được, hoặc chuỗi lý do (message nên được ack và bỏ):
    JOB_NOT_FOUND | DUPLICATE_MESSAGE | JOB_ALREADY_FINISHED | LEASE_HELD."""
    j = {"j": str(job_id)}
    with engine.begin() as c:
        job = c.execute(text("""SELECT status, attempts, max_attempts, (lease_expires_at < now()) AS expired
                                FROM conversion_jobs WHERE id = CAST(:j AS uuid) FOR UPDATE"""), j).first()
        if job is None:
            return "JOB_NOT_FOUND"
        if message_id and c.execute(text("SELECT 1 FROM conversion_attempts WHERE message_id = CAST(:m AS uuid)"),
                                    {"m": str(message_id)}).first():
            return "DUPLICATE_MESSAGE"
        if job.status in ("succeeded", "failed"):
            return "JOB_ALREADY_FINISHED"
        if job.status == "running":
            if not job.expired:
                return "LEASE_HELD"
            if _expire(c, job_id, enqueue=False) == "failed":
                return "JOB_ALREADY_FINISHED"
        elif job.attempts >= job.max_attempts:
            return "JOB_ALREADY_FINISHED"
        attempt_no = c.execute(text("""
            UPDATE conversion_jobs SET status = 'running', attempts = attempts + 1, worker_id = :w,
              lease_expires_at = now() + make_interval(secs => :lease),
              started_at = COALESCE(started_at, now()), error_code = NULL, error_message = NULL,
              updated_at = now()
            WHERE id = CAST(:j AS uuid) RETURNING attempts"""), {**j, "w": worker_id, "lease": lease_seconds}).scalar_one()
        c.execute(text("""
            INSERT INTO conversion_attempts (id, job_id, attempt_no, message_id, worker_id, outcome,
                                             started_at, lease_expires_at)
            VALUES (gen_random_uuid(), CAST(:j AS uuid), :n, CAST(:m AS uuid), :w, 'running', now(),
                    now() + make_interval(secs => :lease))"""),
            {**j, "n": attempt_no, "m": str(message_id) if message_id else None, "w": worker_id,
             "lease": lease_seconds})
        src = c.execute(text("""SELECT s.object_key, s.bucket, s.size_bytes, s.source_checksum, jb.source_format,
                                       jb.original_filename, jb.options
                                FROM source_objects s JOIN conversion_jobs jb ON jb.id = s.job_id
                                WHERE s.job_id = CAST(:j AS uuid)"""), j).mappings().first()
    return {"attempt_no": attempt_no, "source_key": src["object_key"], "source_bucket": src["bucket"],
            "source_size": src["size_bytes"], "source_checksum": src["source_checksum"],
            "format": src["source_format"], "options": src["options"],
            "result_bucket": RESULTS_BUCKET, "result_key": result_key(job_id, attempt_no)}


def heartbeat(job_id, worker_id: str, attempt_no: int, lease_seconds: int = LEASE_SECONDS) -> bool:
    """False = đã mất lease (job thuộc lượt/worker khác): dừng và bỏ kết quả."""
    with engine.begin() as c:
        return c.execute(text("""
            UPDATE conversion_jobs SET lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
            WHERE id = CAST(:j AS uuid) AND status = 'running' AND worker_id = :w AND attempts = :n"""),
            {"j": str(job_id), "w": worker_id, "n": attempt_no, "lease": lease_seconds}).rowcount == 1


def complete(job_id, worker_id: str, attempt_no: int, converter_version: str, size_bytes: int,
             checksum: str, page_count: int, duration_ms: int | None = None) -> bool:
    """Chỉ gọi SAU KHI PDF đã nằm trong bucket results và đọc lại được. False = mất lease."""
    p = {"j": str(job_id), "w": worker_id, "n": attempt_no, "v": converter_version}
    with engine.begin() as c:
        if c.execute(text("""
            UPDATE conversion_jobs SET status = 'succeeded', finished_at = now(), lease_expires_at = NULL,
              converter_version = :v, error_code = NULL, error_message = NULL, updated_at = now()
            WHERE id = CAST(:j AS uuid) AND status = 'running' AND worker_id = :w AND attempts = :n"""),
                p).rowcount == 0:
            return False
        c.execute(text("""
            INSERT INTO result_objects (id, job_id, bucket, object_key, size_bytes, result_checksum,
                                        page_count, converter_version, created_at, expires_at)
            VALUES (gen_random_uuid(), CAST(:j AS uuid), :b, :k, :size, :sum, :pages, :v, now(),
                    now() + make_interval(hours => :ttl))"""),
            {**p, "b": RESULTS_BUCKET, "k": result_key(job_id, attempt_no), "size": size_bytes,
             "sum": checksum, "pages": page_count, "ttl": RESULT_TTL_HOURS})
        c.execute(text("""UPDATE conversion_attempts SET outcome = 'succeeded', finished_at = now(),
                          converter_version = :v, duration_ms = :d
                          WHERE job_id = CAST(:j AS uuid) AND attempt_no = :n"""), {**p, "d": duration_ms})
    return True


def fail(job_id, worker_id: str, attempt_no: int, error_code: str, error_message: str,
         retryable: bool = False, converter_version: str | None = None,
         duration_ms: int | None = None) -> str | None:
    """Trả trạng thái mới ('queued' nếu thử lại, 'failed' nếu kết thúc) hoặc None nếu mất lease."""
    p = {"j": str(job_id), "w": worker_id, "n": attempt_no, "code": error_code,
         "msg": error_message[:2000], "v": converter_version, "d": duration_ms}
    with engine.begin() as c:
        row = c.execute(text("""SELECT attempts, max_attempts FROM conversion_jobs
                                WHERE id = CAST(:j AS uuid) AND status = 'running' AND worker_id = :w
                                  AND attempts = :n FOR UPDATE"""), p).first()
        if row is None:
            return None
        requeue = retryable and row.attempts < row.max_attempts
        c.execute(text("""UPDATE conversion_attempts SET outcome = 'failed', finished_at = now(),
                          error_code = :code, error_message = :msg, converter_version = :v, duration_ms = :d
                          WHERE job_id = CAST(:j AS uuid) AND attempt_no = :n"""), p)
        if requeue:
            sql = "status = 'queued', worker_id = NULL, finished_at = NULL"
        else:
            sql = "status = 'failed', finished_at = now()"
        c.execute(text(f"""UPDATE conversion_jobs SET {sql}, lease_expires_at = NULL, error_code = :code,
                           error_message = :msg, converter_version = COALESCE(:v, converter_version),
                           updated_at = now() WHERE id = CAST(:j AS uuid)"""), p)
        if requeue:
            _enqueue(c, job_id, min(BACKOFF_SECONDS * 2 ** (row.attempts - 1), 300))
        return "queued" if requeue else "failed"


def reclaim_expired(limit: int = 50) -> tuple[int, int]:
    """Thu hồi job running có lease hết hạn. Trả (số job về queued, số job failed)."""
    requeued = failed = 0
    with engine.begin() as c:
        ids = c.execute(text("""SELECT id FROM conversion_jobs WHERE status = 'running'
                                AND lease_expires_at < now() ORDER BY lease_expires_at LIMIT :n
                                FOR UPDATE SKIP LOCKED"""), {"n": limit}).scalars().all()
        for jid in ids:
            if _expire(c, jid) == "queued":
                requeued += 1
            else:
                failed += 1
    return requeued, failed
