from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """Gắn UTC cho datetime không có tzinfo (SQLite khi chạy test)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
