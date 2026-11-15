# Seed script (`data/seed.py`)

Tạo dữ liệu mẫu (người dùng giả, job mẫu) qua API từ bộ file test của Muội (`data/valid`, `data/invalid`, `data/expected.csv`).
**Chạy lại bao nhiêu lần cũng ra cùng kết quả, không tạo job trùng.**

## Chạy

Cần Python 3.9+ (không cần cài thêm thư viện) và API đang chạy ở `http://localhost:8000`.

```bash
python data/seed.py                 # tạo job mẫu
python data/seed.py --verify        # tạo xong, chờ job chạy xong, đối chiếu với expected.csv
python data/seed.py --dry-run       # chỉ in kế hoạch (file nào cho tài khoản nào), không gọi API
```
(Windows nếu `python` không chạy thì dùng `py data/seed.py`.)

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--api-url URL` | Địa chỉ API (mặc định `http://localhost:8000`, hoặc biến `SEED_API_URL`) |
| `--verify` | Chờ job chạy xong rồi đối chiếu `expected.csv` |
| `--timeout N` | Số giây tối đa chờ job (mặc định 120) |
| `--include-slow` | Gửi cả `slow_case.txt` (chỉ đúng mong đợi khi worker đang bật chế độ chuyển đổi chậm; nên dùng `--timeout 300`) |
| `--report FILE` | Ghi kết quả ra JSON, ví dụ `docs/evidence/seed-report.json` |
| `--data-dir DIR` | Thư mục chứa `expected.csv`, `valid/`, `invalid/` (mặc định: thư mục của script) |

Mã thoát: `0` ổn · `1` có file không đúng mong đợi hoặc thiếu file · `2` không kết nối/đăng nhập được.

## Vì sao lặp lại được

- **Tài khoản giả:** dùng `alice` và `bob` do API tạo từ `DEMO_ACCOUNTS` (không tạo user mới). Mật khẩu mặc định khớp cấu hình dev của API; đổi bằng biến `SEED_ACCOUNTS="alice:mk,bob:mk"`.
- **Chia file cố định:** mỗi file gắn cho `alice` hoặc `bob` theo SHA-256 của tên file, nên không phụ thuộc thứ tự, thời gian hay máy chạy. Thêm file mới không làm đổi chủ của file cũ.
- **Không tạo trùng:** API chưa có khoá chống trùng khi tạo job, nên script tự kiểm tra: nếu tài khoản đó đã có job cùng **tên file và cùng SHA-256** thì bỏ qua (`da co`).
- **File bị API từ chối** (rỗng, sai đuôi, trên 10 MB) không tạo job nên chạy lại vẫn bị từ chối y hệt.
- `invalid/toolarge.txt` nằm trong `.gitignore` nên script tự tạo trong bộ nhớ (10 MB + 1 byte), không ghi ra đĩa.

## Cách đối chiếu `expected.csv`

| `expected_status` | Đạt khi |
|---|---|
| `succeeded` | Job `succeeded` và số trang ≥ `expected_min_pages` |
| `rejected` | API từ chối lúc upload (4xx), **hoặc** worker từ chối: job `failed` với `INVALID_FILE`. (API chỉ kiểm tra đuôi file, rỗng và dung lượng; file giả đuôi như `fake_image.png` do worker từ chối) |
| `failed` | Job `failed`; riêng `slow_case.txt` phải là `CONVERSION_TIMEOUT` |

## Làm lại từ đầu

Script không xoá dữ liệu. Muốn xoá sạch rồi seed lại:
```bash
docker compose down -v      # xoá cả dữ liệu
docker compose up -d --build
python data/seed.py --verify
```

## Giới hạn

- `slow_case.txt` mặc định bị bỏ qua vì chỉ đúng mong đợi khi worker ở chế độ chậm.
- Job đã nằm ở `failed` do lỗi tạm thời (ví dụ lúc worker chưa chạy) sẽ không được tạo lại; xoá dữ liệu như trên hoặc retry job đó trên giao diện.
