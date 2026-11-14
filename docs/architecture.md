# Kiến trúc Doc2PDF (bản nháp logic)

> Bản nháp tuần 1. Tên dịch vụ cloud thật, đường mạng, ranh giới tin cậy và miền lỗi sẽ cập nhật khi chốt nền tảng.

## 1. Kiến trúc logic và ánh xạ dịch vụ

```mermaid
flowchart LR
    U[Trình duyệt<br/>User / Operator] -->|HTTPS| FE[Frontend]
    FE -->|HTTPS + token| API[API<br/>FastAPI]
    API -->|xác thực token| AUTH[Identity<br/>OIDC]
    API -->|ghi job + outbox<br/>cùng 1 transaction| DB[(PostgreSQL)]
    API -->|lưu file nguồn<br/>private| OBJ[(Object storage)]
    RELAY[Outbox relay] -->|đọc outbox chưa gửi| DB
    RELAY -->|publish| Q[[Hàng đợi bền<br/>+ dead-letter]]
    Q --> W[Worker<br/>container có giới hạn]
    W -->|lease, attempts, trạng thái| DB
    W -->|đọc nguồn, ghi PDF| OBJ
    API -->|signed URL có hạn| U
```

| Thành phần | Cục bộ (hiện tại) | Cloud (sẽ chọn) |
|---|---|---|
| Frontend / API | Docker, FastAPI | Cloud Run / ECS Fargate / App Service |
| Cơ sở dữ liệu | PostgreSQL 16 (container) | Cloud SQL / RDS / Azure DB for PostgreSQL |
| Object storage | SeaweedFS (S3) | Cloud Storage / S3 / Blob Storage |
| Hàng đợi | RabbitMQ | Pub/Sub / SQS / Service Bus |
| Đăng nhập | JWT giả | Identity Platform / Cognito / Entra External ID |
| Worker chuyển đổi | Container worker | Cloud Run Jobs / Fargate task / Container Apps Jobs |

Mọi truy cập storage, queue, auth đi qua lớp **adapter** (`Storage`, `Queue`, `Auth`) để đổi nền tảng bằng cấu hình.

## 2. Luồng chính (thành công)

```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant D as PostgreSQL
    participant S as Object storage
    participant R as Relay
    participant Q as Queue
    participant W as Worker

    U->>A: Upload file (HTTPS, token)
    A->>A: Validate định dạng, size, magic bytes
    A->>S: Lưu file nguồn (private)
    A->>D: Tạo job (queued) + outbox event (1 transaction)
    A-->>U: Trả job ID
    R->>D: Lấy outbox chưa gửi
    R->>Q: Publish message {job_id, source_key, format}
    Q->>W: Giao message
    W->>D: Nhận job: running, lease_expires_at, attempts+1
    W->>S: Đọc nguồn, chuyển đổi, ghi PDF
    W->>W: Kiểm tra PDF đọc được
    W->>D: succeeded + ResultObject (kèm dedup key)
    W->>Q: Ack sau khi đã ghi DB
    U->>A: Tải kết quả
    A-->>U: Signed URL có hạn
```

## 3. Vòng đời job và phục hồi lỗi

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: worker nhận, đặt lease
    running --> succeeded: PDF hợp lệ
    running --> failed: lỗi chuyển đổi / hết số lần thử
    running --> queued: lease hết hạn hoặc timeout, còn lượt thử
    failed --> queued: operator retry
    succeeded --> [*]
    failed --> [*]
```

| Tình huống | Cách xử lý |
|---|---|
| Message giao lại | Worker kiểm tra dedup key trong DB, bỏ qua nếu đã xử lý |
| Worker bị kill giữa chừng | Lease hết hạn, job quay lại `queued` hoặc `failed` nếu hết lượt thử |
| Chuyển đổi quá chậm | Timeout, dọn dữ liệu tạm, tính là một lần thử |
| Hết số lần thử | Job `failed`, message vào dead-letter, operator thấy và retry |

## 4. Việc còn lại để hoàn thiện bản chính thức

- [ ] Chốt nền tảng cloud và thay tên dịch vụ thật
- [ ] Vẽ đường mạng, ranh giới tin cậy (public/private), miền lỗi
- [ ] Ghi cách kết nối database riêng tư (VPC / connector)
- [ ] Thêm luồng giám sát: log có job ID, dashboard, alert
