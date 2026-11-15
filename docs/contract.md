# Hợp đồng hàng đợi và trạng thái công việc

`schema_version = 1`. **PostgreSQL là nguồn sự thật**; message chỉ đánh thức worker. Message có thể bị giao lặp hoặc đến muộn, nên trạng thái trong DB và các quy tắc dưới đây quyết định kết quả.

## 1. Trạng thái công việc

| Từ | Sang | Sự kiện |
|---|---|---|
| — | `queued` | `POST /jobs` (`attempts = 0`, ghi outbox cùng giao dịch) |
| `queued` | `running` | worker nhận job: `attempts + 1`, đặt `worker_id`, `lease_expires_at` |
| `running` | `running` | heartbeat gia hạn `lease_expires_at` |
| `running` | `succeeded` | PDF đã nằm trong bucket `results` và đọc được; ghi `ResultObject`, `converter_version` |
| `running` | `queued` | lỗi tạm thời (vd timeout) hoặc lease hết hạn, và `attempts < max_attempts`; ghi outbox mới |
| `running` | `failed` | lỗi không thử lại được, hoặc hết `max_attempts` |
| `failed` | `queued` | `POST /jobs/{id}/retry` (`max_attempts = attempts + 3`, ghi outbox mới) |

`succeeded` là trạng thái cuối. Mọi chuyển trạng thái nằm trong **một giao dịch** có khoá dòng job. Job `running` quá lease không bao giờ ở lại mãi: được thu hồi (§3.5).

## 2. Message trong hàng đợi

| Thành phần | Giá trị |
|---|---|
| Exchange | `doc2pdf.jobs` (`direct`, durable) |
| Queue / routing key | `doc2pdf.convert` / `job.convert`; dead-letter: `x-dead-letter-exchange=doc2pdf.dlx`, key `job.convert.dead`, queue `doc2pdf.convert.dead` |
| AMQP | `message_id` = `message_id` bên dưới, `content_type=application/json`, `delivery_mode=2`, `type=job.convert.requested`, header `x-request-id` |

```json
{ "schema_version": 1,
  "message_id": "330e0c09-8212-4337-9f9d-a132dd913fe8",
  "type": "job.convert.requested",
  "job_id": "92a14679-dc4d-4145-b745-50c616657853",
  "source_key": "jobs/92a14679-dc4d-4145-b745-50c616657853/source",
  "format": "txt",
  "request_id": "ca2985cbbc6f4235a17d0ec7d794efda",
  "enqueued_at": "2026-11-15T09:00:00.123456+00:00" }
```

`format` ∈ `txt` · `md` · `png` · `jpg`. `source_key` nằm trong bucket nguồn (`S3_BUCKET_SOURCES`). Tuỳ chọn chuyển đổi, tên file gốc và checksum lấy từ DB (`conversion_jobs`, `source_objects`). Message không chứa nội dung file hay URL.

**Outbox**: API (và bước thu hồi lease) ghi `outbox_events` cùng giao dịch với thay đổi job; `outbox_events.id` chính là `message_id`. Relay đọc sự kiện chưa gửi (`published_at IS NULL AND available_at <= now()`), publish có publisher-confirm, rồi mới đặt `published_at`. Hệ quả: **at-least-once**, consumer phải chịu được message trùng.

## 3. Giao thức worker với PostgreSQL

Worker ghi trực tiếp vào các bảng của `docs/api.md` §2. Dùng đồng hồ PostgreSQL (`now()`). Giá trị chuẩn: lease **60 s**, heartbeat mỗi **20 s**, timeout một lần chuyển đổi **30 s** (nhỏ hơn lease), `max_attempts` **3**, backoff thử lại `min(5·2^(attempt−1), 300)` s, PDF kết quả hết hạn sau **24 h**.

### 3.1 Nhận job (claim), một giao dịch

```sql
SELECT status, attempts, max_attempts, (lease_expires_at < now()) AS expired
  FROM conversion_jobs WHERE id = :job FOR UPDATE;
```
Rồi quyết định theo thứ tự (các trường hợp dừng đều **ack** message):

1. Đã có `conversion_attempts.message_id = :message_id` → **trùng message**, bỏ.
2. `status` là `succeeded` hoặc `failed` → bỏ.
3. `status = 'running'` và lease còn hạn → worker khác đang xử lý, bỏ.
4. `status = 'running'` và lease đã hết hạn → thu hồi job (§3.5) rồi nhận tiếp nếu còn lượt.
5. Ngược lại nhận job:
```sql
UPDATE conversion_jobs SET status='running', attempts=attempts+1, worker_id=:w,
       lease_expires_at = now() + interval '60 seconds', started_at = COALESCE(started_at, now()),
       error_code=NULL, error_message=NULL, updated_at=now()
 WHERE id=:job RETURNING attempts;                       -- = attempt_no
INSERT INTO conversion_attempts (id, job_id, attempt_no, message_id, worker_id, outcome, started_at, lease_expires_at)
VALUES (gen_random_uuid(), :job, :attempt_no, :message_id, :w, 'running', now(), now() + interval '60 seconds');
```
`message_id` UNIQUE là khoá khử trùng lặp, được ghi cùng giao dịch với tiến triển của job.

Khoá PDF đầu ra: bucket `S3_BUCKET_RESULTS`, key `jobs/{job_id}/attempt-{attempt_no}.pdf` (theo lượt nên worker cũ không ghi đè kết quả của lượt mới).

### 3.2 Gia hạn lease (heartbeat)

```sql
UPDATE conversion_jobs SET lease_expires_at = now() + interval '60 seconds', updated_at = now()
 WHERE id=:job AND status='running' AND worker_id=:w AND attempts=:attempt_no;
```
0 dòng bị cập nhật = **đã mất lease**: dừng, bỏ kết quả, không ghi thêm gì.

### 3.3 Thành công

Chỉ khi PDF đã nằm trong bucket `results`, mở được và có ≥ 1 trang:
```sql
UPDATE conversion_jobs SET status='succeeded', finished_at=now(), lease_expires_at=NULL, converter_version=:v,
       error_code=NULL, error_message=NULL, updated_at=now()
 WHERE id=:job AND status='running' AND worker_id=:w AND attempts=:attempt_no;   -- 0 dòng = mất lease, dừng
INSERT INTO result_objects (id, job_id, bucket, object_key, size_bytes, result_checksum, page_count,
                            converter_version, created_at, expires_at)
VALUES (gen_random_uuid(), :job, :bucket, :key, :size, :sha256, :pages, :v, now(), now() + interval '24 hours');
UPDATE conversion_attempts SET outcome='succeeded', finished_at=now(), converter_version=:v, duration_ms=:ms
 WHERE job_id=:job AND attempt_no=:attempt_no;
```

### 3.4 Thất bại

Cùng điều kiện khoá (`status='running' AND worker_id AND attempts`); ghi `conversion_attempts` (`outcome='failed'`, `error_code`, `error_message`, `duration_ms`), rồi:

* **Thử lại** nếu lỗi tạm thời và `attempts < max_attempts`: `status='queued'`, `worker_id=NULL`, `lease_expires_at=NULL`, ghi `error_code/error_message`, thêm một `outbox_events` mới với `available_at = now() + backoff`.
* **Kết thúc** nếu không thử lại được hoặc hết lượt: `status='failed'`, `finished_at=now()`. Nếu hết lượt thử vì lỗi tạm thời, worker **nack không requeue** message để nó vào `doc2pdf.convert.dead` (dead-letter, operator thấy trên RabbitMQ).

Không đưa nội dung file, URL ký hay khoá vào `error_message`.

### 3.5 Thu hồi lease hết hạn

Với mỗi job `status='running' AND lease_expires_at < now()` (`FOR UPDATE SKIP LOCKED`): đóng attempt (`outcome='lease_expired'`, `error_code='LEASE_EXPIRED'`); nếu `attempts < max_attempts` đưa job về `queued` và ghi `outbox_events` mới, ngược lại `failed`. Thao tác idempotent, an toàn khi nhiều tiến trình cùng chạy. Relay chạy bước này định kỳ (mặc định mỗi 10 s) nên cửa sổ phục hồi tối đa ≈ lease + 10 s + độ trễ relay (~70 s); worker cũng được phép tự thu hồi theo cùng quy tắc.

### 3.6 Ack / nack

1. `prefetch_count = 1`, tắt auto-ack.
2. **Ack sau khi tiến triển đã nằm trong DB**: claim bị từ chối (các trường hợp 1–3), hoặc sau khi §3.3 / §3.4 commit.
3. Worker chết trước khi ack: broker giao lại message → trùng `message_id` → bỏ; job được cứu bằng hết lease → thu hồi → message mới.
4. Message sai cấu trúc, `schema_version` lạ hoặc `job_id` không tồn tại → `nack(requeue=false)`.
5. Số lần thử đếm bằng `attempts` trong DB, không dựa vào số lần giao lại của broker.

## 4. Object storage

| Bucket | Khoá | Ghi |
|---|---|---|
| `sources` | `jobs/{job_id}/source` | API; worker chỉ đọc |
| `results` | `jobs/{job_id}/attempt-{n}.pdf` | worker; người dùng chỉ tải qua URL ký ngắn hạn do API cấp |

Không bucket nào công khai.
