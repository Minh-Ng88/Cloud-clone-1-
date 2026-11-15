"""Kiểm thử luồng chính. Cần PostgreSQL (conftest tự tạo DB `<tên DB>_test` và chạy migration)."""
import hashlib
import json
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

import app.storage as storage_module
from app.db import SessionLocal, engine
from app.main import app
from app.models import OutboxEvent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import worker_sim as w  # noqa: E402

# Thu hồi lease do relay thực hiện (relay/reaper.py); chỉ có khi chạy trong repo đầy đủ
_reaper = os.path.join(os.path.dirname(__file__), "..", "..", "relay", "reaper.py")
if os.path.exists(_reaper):
    import importlib.util
    _spec = importlib.util.spec_from_file_location("relay_reaper", _reaper)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    reclaim_expired = _mod.reclaim_expired
else:  # chạy trong image test (không có thư mục relay): dùng bản tham chiếu
    reclaim_expired = lambda engine: w.reclaim_expired()  # noqa: E731

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeStorage:
    def ensure_buckets(self): ...
    def ping(self): return True
    def put_source(self, key, data, ct): ...
    def delete(self, bucket, key): ...
    def presign_download(self, bucket, key, filename, ttl): return f"http://s3/{bucket}/{key}?ttl={ttl}"


@pytest.fixture()
def c(monkeypatch):
    monkeypatch.setattr(storage_module, "_storage", FakeStorage())
    with TestClient(app) as client:
        yield client


def login(c, name, pw):
    r = c.post("/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(c, h, name="a.txt", data=b"xin chao"):
    r = c.post("/jobs", headers=h, files={"file": (name, data, "text/plain")},
               data={"options": json.dumps({"font_size": 12})})
    assert r.status_code == 202, r.text
    return r.json()


def test_upload_status_permissions_and_download(c):
    alice, bob, ops = login(c, "alice", "alice123"), login(c, "bob", "bob123"), login(c, "operator", "operator123")
    job = upload(c, alice)
    jid = job["id"]
    assert job["status"] == "queued" and job["attempts"] == 0
    assert job["source_checksum"] == hashlib.sha256(b"xin chao").hexdigest()

    assert c.get(f"/jobs/{jid}", headers=bob).status_code == 404
    assert c.get(f"/jobs/{jid}", headers=ops).status_code == 200
    assert c.get("/jobs").status_code == 401
    assert c.get("/operator/stats", headers=alice).status_code == 403
    assert c.get(f"/jobs/{jid}/download", headers=alice).status_code == 409  # chưa có PDF

    # Message trong outbox: {job_id, source_key, format}
    with SessionLocal() as db:
        ev = db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == uuid.UUID(jid))).one()
    assert ev.payload["job_id"] == jid and ev.payload["format"] == "txt"
    assert ev.payload["source_key"] == f"jobs/{jid}/source"

    # Worker (giao thức DB): nhận -> gia hạn -> hoàn tất
    mid = uuid.uuid4()
    cl = w.claim(jid, "w1", mid)
    assert cl["attempt_no"] == 1 and cl["format"] == "txt"
    assert w.claim(jid, "w1", mid) == "DUPLICATE_MESSAGE"
    assert w.claim(jid, "w2") == "LEASE_HELD"
    assert c.get(f"/jobs/{jid}", headers=alice).json()["status"] == "running"
    assert w.heartbeat(jid, "w1", 1) and not w.heartbeat(jid, "w2", 1)
    assert w.complete(jid, "w1", 1, "t-1", 5, "a" * 64, 1)
    assert not w.complete(jid, "w1", 1, "t-1", 5, "a" * 64, 1)  # lượt đã kết thúc

    j = c.get(f"/jobs/{jid}", headers=alice).json()
    assert j["status"] == "succeeded" and j["download_available"] and j["converter_version"] == "t-1"
    d = c.get(f"/jobs/{jid}/download", headers=alice)
    assert d.status_code == 200 and d.json()["filename"] == "a.pdf"
    assert c.get(f"/jobs/{jid}/download", headers=bob).status_code == 404
    assert w.claim(jid, "w3") == "JOB_ALREADY_FINISHED"
    assert [a["outcome"] for a in c.get(f"/jobs/{jid}/attempts", headers=alice).json()] == ["succeeded"]


def test_upload_rules_match_reference_dataset(c):
    """Khớp data/expected.csv: 5 file `rejected` bị từ chối ngay khi upload, `corrupt.jpg` được nhận."""
    h = login(c, "alice", "alice123")
    post = lambda name, data: c.post("/jobs", headers=h, files={"file": (name, data)})  # noqa: E731
    code = lambda r: r.json()["error"]["code"]  # noqa: E731
    r = post("empty.txt", b"");                                   assert (r.status_code, code(r)) == (400, "EMPTY_FILE")
    r = post("fake_image.png", b"Day la van ban, khong phai anh"); assert (r.status_code, code(r)) == (422, "INVALID_FILE")
    r = post("exe_renamed.png", b"MZ\x90\x00\x03\x00" + b"\x01" * 64); assert (r.status_code, code(r)) == (422, "INVALID_FILE")
    r = post("unsupported.docx", b"PK\x03\x04" + bytes(64));       assert (r.status_code, code(r)) == (415, "UNSUPPORTED_FORMAT")
    r = post("toolarge.txt", b"A" * (10 * 1024 * 1024 + 1));      assert (r.status_code, code(r)) == (413, "FILE_TOO_LARGE")
    assert code(post("binary.txt", b"abc\x00def")) == "INVALID_FILE"
    assert code(post("latin1.txt", "é".encode("latin-1"))) == "INVALID_FILE"
    assert code(post("fake.jpg", PNG)) == "INVALID_FILE"
    # Được nhận: header đúng nhưng thân hỏng (corrupt.jpg) -> worker sẽ báo failed
    assert post("corrupt.jpg", b"\xff\xd8\xff\xe0" + b"garbage" * 50).status_code == 202
    assert post("ok.png", PNG).status_code == 202
    assert post("tieng_viet.md", "# Xin chào".encode()).status_code == 202
    assert post("crlf.txt", "Dòng 1\r\nDòng 2\r\n".encode()).status_code == 202
    assert post("bom.txt", b"\xef\xbb\xbfxin chao").status_code == 202
    assert c.post("/jobs", headers=h, files={"file": ("a.txt", b"x")}, data={"options": "{bad"}).status_code == 422
    assert c.post("/jobs", files={"file": ("a.txt", b"x")}).status_code == 401  # không token (S1)


def test_failure_retry_and_fencing(c):
    h = login(c, "alice", "alice123")
    jid = upload(c, h)["id"]
    for n in (1, 2, 3):
        assert w.claim(jid, "w1")["attempt_no"] == n
        assert w.fail(jid, "w1", n, "CONVERSION_TIMEOUT", "slow", retryable=True) == ("queued" if n < 3 else "failed")
    j = c.get(f"/jobs/{jid}", headers=h).json()
    assert j["status"] == "failed" and j["error_code"] == "CONVERSION_TIMEOUT" and j["attempts"] == 3
    assert w.fail(jid, "w1", 3, "INTERNAL_ERROR", "x") is None  # worker cũ không ghi được nữa
    with SessionLocal() as db:  # mỗi lần thử lại có một message mới (2 lần retry + 1 lần tạo)
        assert len(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == uuid.UUID(jid))).all()) == 3

    bob = login(c, "bob", "bob123")
    assert c.post(f"/jobs/{jid}/retry", headers=bob).status_code == 403  # user khác retry job người khác (S5)
    r = c.post(f"/jobs/{jid}/retry", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["max_attempts"] == 6
    assert c.post(f"/jobs/{jid}/retry", headers=h).status_code == 409
    # lỗi không retry được (file hỏng) -> failed ngay
    jid2 = upload(c, h)["id"]
    assert w.claim(jid2, "w1")["attempt_no"] == 1
    assert w.fail(jid2, "w1", 1, "INVALID_FILE", "sai magic bytes") == "failed"


def test_lease_expiry_is_reclaimed(c):
    h = login(c, "alice", "alice123")
    ops = login(c, "operator", "operator123")
    jid = upload(c, h)["id"]
    assert w.claim(jid, "dead-worker")["attempt_no"] == 1
    with engine.begin() as conn:  # giả lập worker chết: lease đã hết hạn
        conn.execute(text("UPDATE conversion_jobs SET lease_expires_at = now() - interval '1 second' "
                          "WHERE id = CAST(:j AS uuid)"), {"j": jid})
    assert c.get("/operator/stats", headers=ops).json()["running_with_expired_lease"] >= 1
    requeued, failed = reclaim_expired(engine)  # chính hàm mà relay chạy định kỳ
    assert requeued >= 1
    j = c.get(f"/jobs/{jid}", headers=h).json()
    assert j["status"] == "queued" and j["error_code"] == "LEASE_EXPIRED"
    assert c.get(f"/jobs/{jid}/attempts", headers=h).json()[0]["outcome"] == "lease_expired"
    assert w.claim(jid, "w2")["attempt_no"] == 2
