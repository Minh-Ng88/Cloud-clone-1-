# Frontend Doc2PDF (Nhàn)

HTML + CSS + JavaScript thuần (không cần cài npm). Cần một máy chủ tĩnh vì dùng ES module.

## Chạy

```bash
cd frontend
python -m http.server 5173
```
Mở http://localhost:5173 (cổng 5173 nằm trong CORS của backend).

- Mặc định chạy **chế độ mock** (dữ liệu giả, không cần backend).
- Chạy với backend thật (sau `docker compose up -d --build`): mở http://localhost:5173/?mock=0

Tài khoản demo: `alice/alice123`, `bob/bob123` (người dùng), `operator/operator123` (vận hành).

## Cấu trúc

| File | Việc |
|---|---|
| `js/api.js` | Mọi lệnh gọi API (đổi endpoint chỉ sửa ở đây) |
| `js/session.js` | Lưu token đăng nhập |
| `js/views/login.js` | Màn hình đăng nhập |
| `js/views/home.js` | Trang sau đăng nhập (tạm: số job theo trạng thái) |
| `js/app.js` | Router `#/login`, `#/home` |
| `mock/` | API giả + dữ liệu (xem `mock/README.md`) |

Mock cần trình duyệt hỗ trợ `import ... with { type: "json" }` (Chrome/Edge 123+, Firefox 138+, Safari 17.2+).
