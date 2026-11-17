import os
import sys
import glob
import tempfile
from unittest.mock import MagicMock
import pytest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from validators import InvalidInputError, validate_output_pdf
from converters import convert_with_timeout
from queue_adapter import QueueMessage
from main import Doc2PdfWorker


def _build_mock_worker() -> Doc2PdfWorker:
    worker = Doc2PdfWorker.__new__(Doc2PdfWorker)
    worker.worker_id = "test-worker-01"
    worker.queue = MagicMock()
    worker.api = MagicMock()
    worker.s3 = MagicMock()
    return worker


def test_convert_valid_sample_and_cleanup():
    """Kiểm thử luồng thành công: tải S3 -> convert -> validate PDF -> upload S3 -> complete -> ACK -> xóa temp."""
    worker = _build_mock_worker()
    worker.api.claim_job.return_value = {
        "action": "process",
        "job": {"job_id": "job-ok-1", "source_key": "uploads/sample.txt", "attempts": 1},
    }

    def fake_download(object_key, local_path, bucket=None):
        with open(local_path, "w", encoding="utf-8") as f:
            f.write("Xin chào Việt Nam! Kiểm thử chuyển đổi PDF tuần 2.")
        return local_path

    worker.s3.download_source.side_effect = fake_download

    msg = QueueMessage(
        body={"job_id": "job-ok-1", "source_key": "uploads/sample.txt"},
        message_id="msg-dedup-001",
        raw_handle="handle-1",
    )
    worker.process_message(msg)

    worker.s3.upload_result.assert_called_once()
    worker.api.complete_job.assert_called_once()
    assert worker.api.complete_job.call_args.kwargs["message_id"] == "msg-dedup-001"
    worker.queue.ack.assert_called_once_with(msg)


def test_duplicate_message_id_is_skipped_and_acked():
    """Kiểm thử dedup theo message_id: nếu API báo trùng/đã xong thì bỏ qua và ACK ngay."""
    worker = _build_mock_worker()
    worker.api.claim_job.return_value = {
        "action": "skip_ack",
        "reason": "Duplicate message_id",
    }

    msg = QueueMessage(
        body={"job_id": "job-ok-1", "source_key": "uploads/sample.txt"},
        message_id="msg-dedup-001",
        raw_handle="handle-dup",
    )
    worker.process_message(msg)

    worker.s3.download_source.assert_not_called()
    worker.api.complete_job.assert_not_called()
    worker.queue.ack.assert_called_once_with(msg)


def test_invalid_input_fails_without_retry():
    """Kiểm thử file giả mạo magic bytes -> InvalidInputError -> fail(retryable=False) -> dead_letter."""
    worker = _build_mock_worker()
    worker.api.claim_job.return_value = {
        "action": "process",
        "job": {"job_id": "job-bad-1", "source_key": "uploads/fake.png", "attempts": 1},
    }

    def fake_download_bad_png(object_key, local_path, bucket=None):
        with open(local_path, "wb") as f:
            f.write(b"NOT_A_REAL_PNG_HEADER")
        return local_path

    worker.s3.download_source.side_effect = fake_download_bad_png

    msg = QueueMessage(
        body={"job_id": "job-bad-1", "source_key": "uploads/fake.png"},
        message_id="msg-bad-001",
        raw_handle="handle-bad",
    )
    worker.process_message(msg)

    worker.api.fail_job.assert_called_once()
    kwargs = worker.api.fail_job.call_args.kwargs
    assert kwargs["error_code"] == "INVALID_INPUT"
    assert kwargs["retryable"] is False
    worker.queue.dead_letter.assert_called_once()


def test_timeout_triggers_retry_when_attempts_remaining():
    """Kiểm thử timeout chuyển đổi -> fail(retryable=True) -> requeue khi còn lượt attempt."""
    worker = _build_mock_worker()
    worker.api.claim_job.return_value = {
        "action": "process",
        "job": {"job_id": "job-timeout-1", "source_key": "uploads/normal.txt", "attempts": 1},
    }

    def fake_download_txt(object_key, local_path, bucket=None):
        with open(local_path, "w", encoding="utf-8") as f:
            f.write("Nội dung hợp lệ nhưng giả lập timeout")
        return local_path

    worker.s3.download_source.side_effect = fake_download_txt
    worker.api.fail_job.return_value = {"status": "queued"}

    import main as worker_main
    old_timeout = worker_main.CONVERT_TIMEOUT_SECONDS
    os.environ["WORKER_SIMULATE_SLOW"] = "1"
    worker_main.CONVERT_TIMEOUT_SECONDS = 1
    try:
        msg = QueueMessage(
            body={"job_id": "job-timeout-1", "source_key": "uploads/normal.txt"},
            message_id="msg-timeout-001",
            raw_handle="handle-to",
        )
        worker.process_message(msg)
    finally:
        worker_main.CONVERT_TIMEOUT_SECONDS = old_timeout
        os.environ.pop("WORKER_SIMULATE_SLOW", None)

    worker.api.fail_job.assert_called_once()
    assert worker.api.fail_job.call_args.kwargs["error_code"] == "CONVERT_TIMEOUT"
    worker.queue.nack.assert_called_once_with(msg, requeue=True)


def test_repo_data_samples_if_present():
    """Chạy kiểm thử trực tiếp trên các file mẫu trong data/valid (nếu có trong repo)."""
    repo_root = os.path.dirname(CURRENT_DIR)
    valid_dir = os.path.join(repo_root, "data", "valid")
    if not os.path.isdir(valid_dir):
        pytest.skip("Chưa có thư mục data/valid")

    files = [
        f for f in glob.glob(os.path.join(valid_dir, "*"))
        if os.path.splitext(f)[1].lower() in (".txt", ".md", ".png", ".jpg", ".jpeg")
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        for src in files:
            out_pdf = os.path.join(tmpdir, os.path.basename(src) + ".pdf")
            convert_with_timeout(src, out_pdf, timeout_seconds=15)
            assert validate_output_pdf(out_pdf) >= 1