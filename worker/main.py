import os
import sys
import uuid
import time
import shutil
import socket
import logging
import tempfile
import threading
from dotenv import load_dotenv

# Đảm bảo import được các module cùng thư mục worker/ dù chạy từ root repo hay trong worker/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

load_dotenv()

from queue_adapter import create_queue_adapter, QueueMessage
from api_client import InternalApiClient
from s3_client import S3StorageClient
from converters import convert_with_timeout
from validators import validate_output_pdf, InvalidInputError, InvalidOutputError

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("worker.main")

LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "60"))
HEARTBEAT_INTERVAL = int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "20"))
CONVERT_TIMEOUT_SECONDS = int(os.getenv("WORKER_CONVERT_TIMEOUT", "30"))
MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))


class HeartbeatManager:
    """Thread chạy nền gửi heartbeat định kỳ để gia hạn lease_expires_at trong khi convert."""

    def __init__(self, api: InternalApiClient, job_id: str, worker_id: str, interval: int = 20):
        self.api = api
        self.job_id = job_id
        self.worker_id = worker_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _run(self):
        while not self._stop_event.wait(self.interval):
            ok = self.api.heartbeat(
                job_id=self.job_id,
                worker_id=self.worker_id,
                lease_seconds=LEASE_SECONDS,
            )
            if ok:
                logger.debug(f"[Heartbeat] Gia hạn lease thành công cho job {self.job_id}")


class Doc2PdfWorker:
    def __init__(self):
        self.worker_id = os.getenv(
            "WORKER_ID", f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        )
        self.queue = create_queue_adapter()
        self.api = InternalApiClient()
        self.s3 = S3StorageClient()
        self.s3.ensure_buckets()

    def process_message(self, msg: QueueMessage) -> None:
        payload = msg.body
        job_id = str(payload.get("job_id", "")).strip()
        message_id = msg.message_id

        if not job_id:
            logger.error(f"Message {message_id} thiếu trường job_id -> đẩy vào DLQ")
            self.queue.dead_letter(msg, reason="Missing job_id")
            return

        logger.info(f"Nhận message_id={message_id} cho job_id={job_id}")

        # 1. Claim job, kiểm tra dedup key và đặt lease
        try:
            claim_res = self.api.claim_job(
                job_id=job_id,
                worker_id=self.worker_id,
                message_id=message_id,
                lease_seconds=LEASE_SECONDS,
            )
        except Exception as e:
            logger.error(f"[Job {job_id}] Lỗi gọi API /claim: {e} -> NACK để thử lại")
            time.sleep(2)
            self.queue.nack(msg, requeue=True)
            return

        action = claim_res.get("action")
        if action == "skip_ack":
            logger.info(f"[Job {job_id}] Bỏ qua ({claim_res.get('reason')}) -> ACK")
            self.queue.ack(msg)
            return

        if action == "requeue":
            logger.info(f"[Job {job_id}] Đang được xử lý bởi worker khác ({claim_res.get('reason')}) -> requeue")
            time.sleep(2)
            self.queue.nack(msg, requeue=True)
            return

        job_info = claim_res.get("job", {})
        source_key = payload.get("source_key") or job_info.get("source_key")
        source_bucket = payload.get("source_bucket") or job_info.get("source_bucket")
        result_key = payload.get("result_key") or job_info.get("result_key") or f"{job_id}/output.pdf"
        result_bucket = payload.get("result_bucket") or job_info.get("result_bucket")
        attempts = int(job_info.get("attempts", 1))

        if not source_key:
            self._handle_failure(
                msg=msg,
                job_id=job_id,
                message_id=message_id,
                error_code="MISSING_SOURCE_KEY",
                error_message="Thiếu source_key trong message và database.",
                retryable=False,
                attempts=attempts,
            )
            return

        # 2. Tạo thư mục tạm riêng biệt cho job này (luôn dọn dẹp ở khối finally)
        work_dir = tempfile.mkdtemp(prefix=f"doc2pdf_{job_id}_")
        hb = HeartbeatManager(self.api, job_id=job_id, worker_id=self.worker_id, interval=HEARTBEAT_INTERVAL)
        hb.start()

        try:
            filename = os.path.basename(source_key)
            local_input = os.path.join(work_dir, filename)
            local_output = os.path.join(work_dir, f"{job_id}.pdf")

            # 3. Tải file nguồn từ S3
            self.s3.download_source(object_key=source_key, local_path=local_input, bucket=source_bucket)

            # 4. Chuyển đổi sang PDF có giới hạn timeout (30s)
            convert_with_timeout(
                input_path=local_input,
                output_path=local_output,
                timeout_seconds=CONVERT_TIMEOUT_SECONDS,
            )

            # 5. Kiểm tra PDF đầu ra đọc được và có >= 1 trang trước khi báo succeeded
            page_count = validate_output_pdf(local_output)
            pdf_size = os.path.getsize(local_output)

            # 6. Upload PDF kết quả lên S3
            self.s3.upload_result(local_path=local_output, object_key=result_key, bucket=result_bucket)

            # 7. Báo API hoàn thành job (ghi cùng dedup key message_id)
            self.api.complete_job(
                job_id=job_id,
                worker_id=self.worker_id,
                message_id=message_id,
                result_key=result_key,
                page_count=page_count,
                file_size=pdf_size,
            )

            logger.info(
                f"[Job {job_id}] Hoàn thành thành công! ({page_count} trang, {pdf_size} bytes) -> ACK"
            )
            self.queue.ack(msg)

        except InvalidInputError as e:
            # Lỗi đầu vào không hợp lệ -> không retry vô ích, chốt failed ngay
            self._handle_failure(
                msg=msg,
                job_id=job_id,
                message_id=message_id,
                error_code="INVALID_INPUT",
                error_message=str(e),
                retryable=False,
                attempts=attempts,
            )
        except TimeoutError as e:
            # Lỗi quá thời gian chuyển đổi (ví dụ slow_case.txt)
            self._handle_failure(
                msg=msg,
                job_id=job_id,
                message_id=message_id,
                error_code="CONVERT_TIMEOUT",
                error_message=str(e),
                retryable=True,
                attempts=attempts,
            )
        except InvalidOutputError as e:
            self._handle_failure(
                msg=msg,
                job_id=job_id,
                message_id=message_id,
                error_code="INVALID_OUTPUT_PDF",
                error_message=str(e),
                retryable=True,
                attempts=attempts,
            )
        except Exception as e:
            # Lỗi hệ thống/mạng/S3 tạm thời -> cho phép retry nếu còn lượt
            self._handle_failure(
                msg=msg,
                job_id=job_id,
                message_id=message_id,
                error_code="WORKER_ERROR",
                error_message=str(e),
                retryable=True,
                attempts=attempts,
            )
        finally:
            hb.stop()
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.debug(f"[Job {job_id}] Đã dọn dẹp thư mục tạm {work_dir}")

    def _handle_failure(
        self,
        msg: QueueMessage,
        job_id: str,
        message_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        attempts: int,
    ) -> None:
        can_retry = retryable and (attempts < MAX_ATTEMPTS)
        logger.warning(
            f"[Job {job_id}] Lỗi {error_code} (attempt {attempts}/{MAX_ATTEMPTS}, retry={can_retry}): {error_message}"
        )
        try:
            fail_res = self.api.fail_job(
                job_id=job_id,
                worker_id=self.worker_id,
                message_id=message_id,
                error_code=error_code,
                error_message=error_message,
                retryable=can_retry,
            )
            new_status = fail_res.get("status", "failed" if not can_retry else "queued")
        except Exception as api_err:
            logger.error(f"[Job {job_id}] Không gọi được API /fail: {api_err}")
            new_status = "queued" if can_retry else "failed"

        if can_retry and new_status == "queued":
            time.sleep(2)
            self.queue.nack(msg, requeue=True)
        else:
            # Hết lượt retry hoặc lỗi không thể retry -> ACK/dead-letter để không lặp vô tận
            self.queue.dead_letter(msg, reason=f"{error_code}: {error_message}")

    def run(self) -> None:
        logger.info(f"Khởi động Worker Consumer (worker_id={self.worker_id})...")
        try:
            self.queue.consume(self.process_message)
        finally:
            self.api.close()
            self.queue.close()


if __name__ == "__main__":
    worker = Doc2PdfWorker()
    worker.run()