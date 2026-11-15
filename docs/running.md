# Chạy và kiểm thử API + relay

Cần Git và Docker Desktop (đang chạy). Lệnh dưới đây cho PowerShell; macOS/Linux dùng `cp` thay `copy`.

## 1. Khởi động

```powershell
copy .env.example .env
docker compose up -d --build
docker compose ps
```

`docker-compose.override.yml` (nằm cạnh `docker-compose.yml`) được Docker Compose **tự động gộp**, thêm dịch vụ `api` (chạy migration rồi mở cổng 8000) và `relay`. `api` phải `healthy` trước khi `relay` chạy.

| Dịch vụ | Địa chỉ |
|---|---|
| API (Swagger) | http://localhost:8000/docs · kiểm tra: http://localhost:8000/ready |
| RabbitMQ UI | http://localhost:15672 |
| Frontend nối API thật | mở frontend với `?mock=0` (CORS cho phép cổng 5173 và 3000) |

Tài khoản demo: `alice/alice123`, `bob/bob123` (user), `operator/operator123` (operator).

## 2. Kiểm thử

| Mục đích | Lệnh |
|---|---|
| Toàn tuyến: upload → outbox → relay → RabbitMQ → worker giả lập → tải PDF, phân quyền, retry, phục hồi lease (~15 s) | `docker compose exec api python scripts/smoke_test.py` |
| Test tự động của API (DB riêng, tự chạy migration) | `docker compose --profile test run --rm api-test` |
| Đối chiếu `data/expected.csv` (Test 2) | `python data/generate.py` rồi `python api/scripts/check_reference.py --data data` |
| Như trên và kiểm kết quả cuối (cần worker đang chạy) | thêm `--wait` |

`smoke_test.py` tự đóng vai worker nên không cần worker thật. Dòng cuối mong đợi: `TẤT CẢ ĐỀU ĐẠT`.
`check_reference.py` không có `--wait` chỉ kiểm phản hồi lúc upload (5 file `rejected` phải bị từ chối, các file còn lại được nhận). Mỗi lần chạy tạo job thật cho `alice`.

## 3. Chạy không qua Docker (khi sửa code)

```powershell
docker compose up -d postgres s3 rabbitmq
cd api
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
pytest -q
```
Relay: `cd relay ; pip install -r requirements.txt ; python main.py`. Cấu hình đọc từ `.env` hoặc biến môi trường (mặc định trỏ `localhost`, khớp `.env.example`).

## 4. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `env file .env not found` | Chưa `copy .env.example .env` |
| `port is already allocated` | Đổi cổng trong `.env` hoặc tắt chương trình đang chiếm cổng |
| Đổi `POSTGRES_PASSWORD` mà API báo sai mật khẩu | Postgres chỉ đặt mật khẩu lần đầu; chạy `docker compose down -v` rồi `up` lại |
| Tải PDF bằng URL ký không mở được | `S3_PUBLIC_ENDPOINT` phải là địa chỉ trình duyệt truy cập được (mặc định `http://localhost:8333`) |

Lưu ý: SeaweedFS cục bộ chưa bật xác thực S3 nên bucket chỉ "riêng tư" ở mức ứng dụng (API không trả URL công khai); kiểm tra S8 của `docs/test-plan.md` cần làm trên cloud.
