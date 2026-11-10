# Doc2PDF-Cloud-Final
Document conversion web service - Cloud Computing final project

## Chạy hạ tầng cục bộ

```bash
copy .env.example .env      # Windows (macOS/Linux: cp .env.example .env)
docker compose up -d
docker compose ps
```

| Dịch vụ | Địa chỉ | Tài khoản |
|---|---|---|
| PostgreSQL | localhost:5432 | xem `.env` |
| S3 (SeaweedFS) | localhost:8333 | không có giao diện web |
| RabbitMQ UI | http://localhost:15672 | xem `.env` |

Tắt: `docker compose down` (thêm `-v` để xóa cả dữ liệu).

## Quy ước làm việc

- **Không push thẳng vào `main`.**
- Tạo nhánh: `feature/ten-viec` (sửa lỗi: `fix/ten-loi`).
- Mở Pull Request, cần **1 người review** trước khi merge.
- PR ghi `Closes #số-issue` hoặc tick việc trong Issue của mình.
- Commit ngắn gọn, rõ nghĩa, ví dụ: `Add TXT to PDF converter`.
- **Không commit** `.env`, mật khẩu, key. Chỉ commit `.env.example`.
- Việc nào bị kẹt thì kéo sang **Blocked** trên board và nhắn nhóm.
- Họp ngắn 10-15 phút mỗi 2 ngày.

## Cấu trúc thư mục

| Thư mục | Phụ trách |
|---|---|
| `api/` | Khôi: FastAPI |
| `worker/` | Lộc: converter, lease, retry |
| `relay/` | Khôi/Lộc: outbox relay |
| `frontend/` | Nhàn: giao diện |
| `infra/` | Như: Terraform, CI/CD |
| `data/` | Muội: file test, seed, backup |
| `docs/` | Cả nhóm: tài liệu |