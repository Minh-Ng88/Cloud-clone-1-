"""Đối chiếu API với bộ dữ liệu tham chiếu data/expected.csv (Test 2 trong docs/test-plan.md).

  expected_status = rejected   -> API phải TỪ CHỐI ngay khi upload (HTTP 4xx), không tạo job
  expected_status = succeeded  -> API nhận (202); với --wait: job phải `succeeded`, số trang >= expected_min_pages
  expected_status = failed     -> API nhận (202); với --wait: job phải kết thúc `failed`

Chạy từ thư mục gốc repo (API đang chạy; --wait cần worker đang chạy):
    python api/scripts/check_reference.py --data data [--wait]
Chỉ dùng thư viện chuẩn. File thiếu (vd data/invalid/toolarge.txt do `python data/generate.py` sinh ra) bị bỏ qua.
Mỗi lần chạy tạo job thật cho tài khoản alice.
"""
import argparse
import csv
import os
import sys
import time

from _http import API_URL, call, login, upload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="thư mục chứa valid/, invalid/ và expected.csv")
    ap.add_argument("--csv", help="đường dẫn expected.csv (mặc định <data>/expected.csv)")
    ap.add_argument("--user", default="alice")
    ap.add_argument("--password", default="alice123")
    ap.add_argument("--wait", action="store_true", help="chờ job kết thúc (cần worker chạy)")
    ap.add_argument("--timeout", type=int, default=240, help="giây chờ tối đa cho cả đợt (--wait)")
    a = ap.parse_args()
    csv_path = a.csv or os.path.join(a.data, "expected.csv")
    if not os.path.exists(csv_path):
        print(f"Không thấy {csv_path}. Dùng --csv hoặc --data.")
        return 2

    token = login(a.user, a.password)
    rows, pending, bad, skipped = [], {}, 0, 0
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            path = os.path.join(a.data, row["filename"])
            if not os.path.exists(path):
                print(f"{row['filename']:34} BỎ QUA (thiếu file; chạy `python data/generate.py`)")
                skipped += 1
                continue
            with open(path, "rb") as fh:
                status, body = upload(token, os.path.basename(path), fh.read())
            code = body.get("error", {}).get("code", "") if isinstance(body, dict) else ""
            exp = row["expected_status"]
            if exp == "rejected":
                ok = 400 <= status < 500
            else:
                ok = status == 202
            rows.append([row["filename"], exp, f"{status} {code}".strip(), "OK" if ok else "SAI", row])
            if ok and status == 202 and a.wait:
                pending[body["id"]] = rows[-1]
            bad += not ok

    deadline = time.time() + a.timeout
    while pending and time.time() < deadline:
        for jid, r in list(pending.items()):
            _, job = call("GET", f"/jobs/{jid}", token)
            if job.get("status") in ("succeeded", "failed"):
                exp, row = r[1], r[4]
                pages = (job.get("result") or {}).get("page_count") or 0
                ok = job["status"] == exp and (exp != "succeeded" or pages >= int(row["expected_min_pages"] or 0))
                r[2] = f"202 -> {job['status']}" + (f" ({pages} trang)" if pages else "") + \
                       (f" {job.get('error_code')}" if job.get("error_code") else "")
                r[3] = "OK" if ok else "SAI"
                bad += not ok
                del pending[jid]
        if pending:
            time.sleep(2)
    for jid, r in pending.items():
        r[3] = "CHƯA XONG"
        bad += 1

    print(f"API: {API_URL}\n{'file':34} {'mong đợi':10} {'thực tế':34} kết quả")
    for r in rows:
        print(f"{r[0]:34} {r[1]:10} {r[2]:34} {r[3]}")
    print(f"\nSai: {bad}, bỏ qua: {skipped}" + ("" if a.wait else "  (chưa kiểm kết quả cuối; dùng --wait khi có worker)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
