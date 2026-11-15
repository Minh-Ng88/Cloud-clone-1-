# Kế hoạch kiểm thử (bản nháp)

> Các con số đánh dấu **(đề xuất)** cần cả nhóm chốt, nhất là Khôi (API) và Lộc (worker). Đề nói rõ đây là tiêu chí lớp học, thay đổi khối lượng hoặc mục tiêu phải thống nhất với giảng viên trước khi test.
> Với mỗi lần test: lưu **dữ liệu đầu vào, thời gian (timestamp), kết quả thô và log liên quan** vào `docs/evidence/`.

## Giá trị cần chốt

| Tham số | Đề xuất | Chốt bởi |
|---|---|---|
| Thời gian lease của worker | 60 giây | Lộc |
| Timeout một lần chuyển đổi | 30 giây | Lộc |
| Số lần thử tối đa | 3 | Khôi + Lộc |
| Cửa sổ phục hồi (khai báo cho Test 3) | lease + 60 giây, ví dụ 2 phút | Cả nhóm |
| Thời hạn signed URL tải PDF | 10 phút | Khôi |
| Giới hạn file | 10 MB | Theo đề |

## Test 1: Trả job ID nhanh

**Mục tiêu:** API trả job ID bền trong **2 giây** (không tính thời gian upload) trong môi trường test đã nêu.

| Mục | Nội dung |
|---|---|
| Cách làm | Gửi 30 request tạo job với file nhỏ (từ `data/valid`), đo thời gian từ lúc API nhận xong file đến lúc trả job ID |
| Kiểm tra thêm | Job ID có trong DB ngay (trạng thái `queued`), tra lại bằng endpoint xem trạng thái |
| Đạt khi | p95 ≤ 2 giây, không request nào lỗi |
| Ghi lại | Môi trường (cục bộ hay cloud, region, tier), số mẫu, p50, p95, tỉ lệ lỗi, file kết quả thô |

## Test 2: Chuyển đổi đúng, file lỗi không ảnh hưởng job khác

**Dữ liệu:** `data/valid` (20 file) và `data/invalid` (7 file), đối chiếu với `data/expected.csv`.

| Bước | Nội dung |
|---|---|
| 1 | Gửi toàn bộ 27 file (xen kẽ file hợp lệ và file lỗi) |
| 2 | Với mỗi file, so sánh trạng thái thực tế với `expected_status` (`succeeded` / `rejected` / `failed`) |
| 3 | Tải từng PDF của job `succeeded`, **mở bằng trình đọc PDF**, kiểm tra nội dung (đặc biệt tiếng Việt có dấu) và số trang ≥ `expected_min_pages` |
| 4 | Xác nhận file lỗi không làm hỏng hay chậm job khác (job hợp lệ gửi sau file lỗi vẫn `succeeded`) |

**Đạt khi:** 20/20 file hợp lệ ra PDF đọc được, 5 file bị từ chối với lý do rõ, `corrupt.jpg` thất bại có chẩn đoán, không job nào kẹt ở `running`.
**Ghi lại:** bảng đối chiếu (file, mong đợi, thực tế, đạt/không), ảnh chụp vài PDF, log theo job ID.

## Test 3: Kill worker, lease hết hạn, job được phục hồi

| Bước | Nội dung |
|---|---|
| 1 | Gửi một job chuyển đổi chậm (dùng `slow_case.txt` hoặc chế độ chậm của worker) |
| 2 | Khi job ở `running`, ghi timestamp rồi **kill container worker** (ví dụ `docker kill`) |
| 3 | Quan sát: `lease_expires_at` trôi qua, job quay lại `queued` (còn lượt thử) hoặc `failed` (hết lượt) |
| 4 | Ghi timestamp lúc job phục hồi, tính thời gian từ lúc kill |

**Đạt khi:** job được thử lại hoặc chuyển `failed` **trong cửa sổ phục hồi đã khai báo**, không ở `running` mãi.
**Ghi lại:** timestamp từng bước, giá trị `attempts` trước và sau, log worker và API theo job ID.

## Bài tập lỗi bắt buộc: chuyển đổi chậm và timeout

| Bước | Nội dung |
|---|---|
| 1 | Bật chế độ chuyển đổi chậm cố ý (dài hơn timeout) |
| 2 | Worker dừng chuyển đổi khi chạm timeout |
| 3 | Dữ liệu tạm bị dọn, job không còn `running` |
| 4 | Metric timeout tăng và **alert kích hoạt** |

**Ghi lại cho alert:** điều kiện, cửa sổ đánh giá, độ trễ dự kiến, hành động khắc phục đầu tiên.

## Kiểm tra bảo mật: gọi thẳng API (không chỉ qua giao diện)

Dùng `curl` hoặc Postman, **không dùng trình duyệt**. Mỗi dòng ghi kết quả thực tế và mã HTTP.

| # | Tình huống | Mong đợi |
|---|---|---|
| S1 | Gọi API không có token | 401 |
| S2 | Token sai hoặc hết hạn | 401 |
| S3 | User A xem job của user B | 403 hoặc 404 |
| S4 | User A tải PDF của user B | 403 hoặc 404 |
| S5 | User thường gọi endpoint operator (danh sách mọi job, retry job người khác) | 403 |
| S6 | Operator gọi endpoint operator | 200 |
| S7 | Dùng lại signed URL sau khi hết hạn | Bị từ chối |
| S8 | Truy cập trực tiếp object trong storage bằng URL công khai | Bị từ chối (storage private) |
| S9 | Upload file quá 10 MB | Bị từ chối |
| S10 | Upload file sai định dạng hoặc giả đuôi | Bị từ chối |
| S11 | Gọi retry trên job đang `succeeded` hoặc `running` | Bị từ chối hoặc không đổi trạng thái |

## Các kiểm tra chung

- [ ] **HTTPS:** chỉ có điểm vào HTTPS, HTTP bị chuyển hướng hoặc từ chối
- [ ] **Bí mật:** không có mật khẩu, key trong repo, image hay log (quét `git log` và log ứng dụng)
- [ ] **Log:** không ghi signed URL, token, nội dung file riêng tư; có job ID xuyên suốt API, worker
- [ ] **Storage private:** không có object công khai
- [ ] **Hạ tầng bằng code:** tạo lại toàn bộ từ Terraform
- [ ] **CI/CD:** triển khai tự động và **demo rollback**
- [ ] **Giao lại message:** gửi trùng một message, kết quả chỉ ghi một lần (dedup key)

## Load test nhỏ (khi đã có cloud)

Khai báo trước khi chạy: **thời lượng, mức đồng thời hoặc request/giây, warmup, bộ dữ liệu, tỉ lệ lỗi**. Báo cáo **p95 từ một mẫu xác định** (nêu số mẫu).

## Mẫu bảng ghi kết quả

| Test | Ngày giờ | Môi trường | Dữ liệu | Kết quả | Đạt? | Đường dẫn bằng chứng |
|---|---|---|---|---|---|---|
| T1 | | | | | | |
| T2 | | | | | | |
| T3 | | | | | | |
| Drill timeout | | | | | | |
| S1–S11 | | | | | | |
