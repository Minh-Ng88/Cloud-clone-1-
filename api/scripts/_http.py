"""Tiện ích HTTP chỉ dùng thư viện chuẩn (không cần cài thêm gì)."""
import json
import os
import urllib.error
import urllib.request
import uuid

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def call(method: str, path: str, token: str | None = None, body: dict | None = None,
         headers: dict | None = None, raw: bytes | None = None, content_type: str | None = None):
    h = dict(headers or {})
    data = raw
    if body is not None:
        data, content_type = json.dumps(body).encode(), "application/json"
    if content_type:
        h["Content-Type"] = content_type
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API_URL + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except ValueError:
            return e.code, {"raw": payload[:200].decode("utf-8", "replace")}
    except urllib.error.URLError as e:
        raise SystemExit(f"Không kết nối được API tại {API_URL} ({e.reason}). "
                         f"Đã chạy `docker compose up -d --build` và đợi api healthy chưa?")


def login(username: str, password: str) -> str:
    status, body = call("POST", "/auth/login", body={"username": username, "password": password})
    if status != 200:
        raise SystemExit(f"Đăng nhập {username} thất bại: {status} {body}")
    return body["access_token"]


def upload(token: str, filename: str, data: bytes, options: dict | None = None):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n'.encode(), data, b"\r\n"]
    if options:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="options"\r\n\r\n'
                     f'{json.dumps(options)}\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    return call("POST", "/jobs", token, raw=b"".join(parts),
                content_type=f"multipart/form-data; boundary={boundary}")
