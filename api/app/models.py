"""Mô hình dữ liệu: ConversionJob, SourceObject, ResultObject (+ ConversionAttempt, OutboxEvent)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.timeutil import now_utc

JSONType = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"
JOB_STATUSES = (QUEUED, RUNNING, SUCCEEDED, FAILED)


class Base(DeclarativeBase):
    pass


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="ck_jobs_status"),
        Index("ix_jobs_owner_created", "owner_id", "created_at"),
        Index("ix_jobs_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default=QUEUED, server_default=QUEUED)
    source_format: Mapped[str] = mapped_column(String(8))  # txt | md | png | jpg
    original_filename: Mapped[str] = mapped_column(String(255))
    options: Mapped[dict] = mapped_column(JSONType, default=dict)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TS)
    source_checksum: Mapped[str] = mapped_column(String(64))  # sha256 hex, bất biến
    converter_version: Mapped[str | None] = mapped_column(String(64))

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(TS, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now_utc, onupdate=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)

    source: Mapped[SourceObject | None] = relationship(
        back_populates="job", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    result: Mapped[ResultObject | None] = relationship(
        back_populates="job", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    attempt_log: Mapped[list[ConversionAttempt]] = relationship(
        back_populates="job", order_by="ConversionAttempt.attempt_no", cascade="all, delete-orphan"
    )


class SourceObject(Base):
    __tablename__ = "source_objects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversion_jobs.id", ondelete="CASCADE"), unique=True
    )
    bucket: Mapped[str] = mapped_column(String(63))
    object_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(128))  # do client khai báo
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    source_checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=now_utc)

    job: Mapped[ConversionJob] = relationship(back_populates="source")


class ResultObject(Base):
    __tablename__ = "result_objects"
    __table_args__ = (Index("ix_results_expires", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversion_jobs.id", ondelete="CASCADE"), unique=True
    )
    bucket: Mapped[str] = mapped_column(String(63))
    object_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    result_checksum: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    converter_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(TS)
    deleted_at: Mapped[datetime | None] = mapped_column(TS)

    job: Mapped[ConversionJob] = relationship(back_populates="result")


class ConversionAttempt(Base):
    """Mỗi lần worker nhận (claim) job tạo một dòng. message_id UNIQUE = khóa khử trùng lặp."""

    __tablename__ = "conversion_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_no", name="uq_attempt_job_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversion_jobs.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    worker_id: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|failed|lease_expired
    started_at: Mapped[datetime] = mapped_column(TS, default=now_utc)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    converter_version: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    job: Mapped[ConversionJob] = relationship(back_populates="attempt_log")


class OutboxEvent(Base):
    """Ghi cùng giao dịch với thay đổi job; relay đọc và đẩy sang RabbitMQ. id = message_id."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_pending", "available_at", postgresql_where=text("published_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(TS, default=now_utc)
    available_at: Mapped[datetime] = mapped_column(TS, default=now_utc)
    published_at: Mapped[datetime | None] = mapped_column(TS)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
