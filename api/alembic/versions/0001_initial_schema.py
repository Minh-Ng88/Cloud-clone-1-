"""Lược đồ ban đầu: conversion_jobs, source_objects, result_objects, conversion_attempts, outbox_events

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("source_format", sa.String(8), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("lease_expires_at", TS),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("converter_version", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_jobs_status"
        ),
    )
    op.create_index("ix_jobs_owner_created", "conversion_jobs", ["owner_id", "created_at"])
    op.create_index("ix_jobs_status_lease", "conversion_jobs", ["status", "lease_expires_at"])

    op.create_table(
        "source_objects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("conversion_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("bucket", sa.String(63), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )

    op.create_table(
        "result_objects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("conversion_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("bucket", sa.String(63), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("result_checksum", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("converter_version", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("deleted_at", TS),
    )
    op.create_index("ix_results_expires", "result_objects", ["expires_at"])

    op.create_table(
        "conversion_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("conversion_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Uuid(), unique=True),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="running"),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("lease_expires_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("converter_version", sa.String(64)),
        sa.Column("duration_ms", sa.Integer()),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_attempt_job_no"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("available_at", TS, nullable=False),
        sa.Column("published_at", TS),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["available_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("conversion_attempts")
    op.drop_table("result_objects")
    op.drop_table("source_objects")
    op.drop_table("conversion_jobs")
