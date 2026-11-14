# Dữ liệu mock cho frontend

Bám theo `docs/api.md` và code backend của Khôi (PR #10). Backend thật chạy ở http://localhost:8000.
Sinh lại dữ liệu: `node frontend/mock/generate.mjs` (kết quả luôn giống nhau).
Dùng: `import { mockFetch } from "./mock/handlers.js"` rồi gọi thay cho `fetch`.

Tài khoản demo: `alice/alice123`, `bob/bob123` (user), `operator/operator123` (operator).
Header: `Authorization: Bearer <access_token>`. Lỗi luôn có dạng `{"error":{"code","message","request_id","details?"}}`.

| Endpoint | Ai gọi | Ghi chú |
|---|---|---|
| `POST /auth/login` `{username,password}` | mọi người | 200 `{access_token,token_type,expires_in,user}`; 401 `INVALID_CREDENTIALS` |
| `GET /auth/me` | đã đăng nhập | `{user_id, role}` |
| `POST /jobs` (multipart: `file`, `options` JSON tùy chọn) | user | 202 + job; **upload và tạo job là một bước** |
| `GET /jobs?status=&limit=&offset=` | user | chỉ job của mình; `{items,total,limit,offset}` |
| `GET /jobs/{id}` | chủ job/operator | job của người khác -> 404 |
| `GET /jobs/{id}/attempts` | chủ job/operator | lịch sử các lần worker thử |
| `POST /jobs/{id}/retry` | chủ job/operator | chỉ job `failed`, 202; khác -> 409 `INVALID_STATE` |
| `GET /jobs/{id}/download` | chủ job/operator | `{download_url,url_expires_in,result_expires_at,filename}`; 409 `RESULT_NOT_READY`; 410 `RESULT_EXPIRED` |
| `GET /operator/jobs`, `/operator/stats`, `/operator/outbox` | operator | user thường -> 403 `FORBIDDEN` |

Trạng thái job: `queued`, `running`, `succeeded`, `failed`.
Mã lỗi job (`error_code`): INVALID_FILE, UNSUPPORTED_FORMAT, FILE_TOO_LARGE, CONVERSION_TIMEOUT, CONVERSION_ERROR, OUTPUT_INVALID, LEASE_EXPIRED, INTERNAL_ERROR.
Lỗi upload: 400 `EMPTY_FILE`, 413 `FILE_TOO_LARGE` (> 10 MB), 415 `UNSUPPORTED_FORMAT` (chỉ txt, md, png, jpg/jpeg), 422 `INVALID_OPTIONS`.
`options`: `page_size` A4|LETTER, `orientation` portrait|landscape, `font_size` 8-24, `margin_mm` 5-40.

Mock: job tạo mới tự chạy queued (2s) -> running (3s) -> succeeded (tên file chứa "hong" hoặc "loi" thì failed).
`data/reference-files.json`: 20 file hợp lệ + 6 file lỗi (3 bị từ chối lúc upload, 3 làm job failed), dùng lại cho seed script.
Không mock `/internal/*` (chỉ worker dùng).

Ghi chú khi nối backend thật:
- CORS chỉ cho phép `http://localhost:5173` (Vite) và `http://localhost:3000`; chạy frontend ở một trong hai cổng này.
- `download_url` là URL S3 ký sẵn, sống 300 giây: mở ngay, không lưu, không ghi log; cần tải lại thì gọi lại `/download`.
- Tải PDF xong mới biết file hỏng hay không là do worker; file giả đuôi (đổi đuôi) vẫn upload được, job sẽ `failed` với `INVALID_FILE`.
- Frontend nên dựa vào `error.code`, không dựa vào `error.message`.
- Có thể gửi `X-Request-ID`; API trả lại header này (dùng để truy vết).

Chi tiết job trong mock:
- Retry job `failed`: tên file bị hỏng (`INVALID_FILE`) thì thử lại vẫn lỗi; lỗi khác (ví dụ `CONVERSION_TIMEOUT`) thì thử lại thành công sau vài giây.
- `GET /jobs/{id}/download` trả một PDF tối giản thật (data URL) nên bấm Tải PDF sẽ tải được file ở chế độ mock.
- `GET /jobs/{id}/attempts` có thêm lịch sử cho job chạy/retry trong phiên mock.
