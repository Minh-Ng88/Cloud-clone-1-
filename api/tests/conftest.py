"""Chuẩn bị DB riêng cho test (<tên DB>_test) trước khi import ứng dụng.

Chỉ cần PostgreSQL chạy được (docker compose up -d postgres). Không đụng vào dữ liệu DB dev.
DATABASE_URL lấy từ biến môi trường / .env, mặc định giống .env.example.
"""
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings

_base = make_url(Settings().database_url)
_test_name = f"{_base.database}_test"
_test_url = _base.set(database=_test_name)


def _prepare_database() -> None:
    admin = create_engine(_base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"),
                           {"n": _test_name}).scalar()
        if not exists:
            c.execute(text(f'CREATE DATABASE "{_test_name}"'))
    admin.dispose()
    os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")  # luôn bắt đầu từ DB sạch; kiểm luôn migration lên/xuống
    command.upgrade(cfg, "head")


_prepare_database()
