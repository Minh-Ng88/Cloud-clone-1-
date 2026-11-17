import os
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger("worker.api")


class InternalApiClient:
    """Client giao tiếp với Backend API qua các endpoint nội bộ theo docs/contract.md."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        service_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.service_key = service_key or os.getenv("INTERNAL_SERVICE_KEY", "dev-internal-key")
        self.headers = {
            "Content-Type": "application/json",
            "X-Service-Key": self.service_key,
        }
        self.client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=timeout)

    def claim_job(self, job_id: str, worker_id: str, message_id: str, lease_seconds: int = 60) -> Dict[str, Any]:
        """
        Claim job để xử lý, đặt lease_expires_at và tăng attempts.
        Trả về dict mô tả hành động:
        - {"action": "process", "job": ...}: được phép chạy
        - {"action": "skip_ack", "reason": ...}: đã xử lý (dedup/succeeded/failed) -> ACK bỏ qua
        - {"action": "requeue", "reason": ...}: đang bị worker khác giữ lease -> NACK/đợi
        """
        url = f"/api/internal/jobs/{job_id}/claim"
        payload = {
            "worker_id": worker_id,
            "message_id": message_id,
            "lease_seconds": lease_seconds,
        }
        resp = self.client.post(url, json=payload)

        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "running")
            if status in ("succeeded", "failed") or data.get("duplicate"):
                return {"action": "skip_ack", "reason": f"Job đã ở trạng thái {status} hoặc trùng message_id"}
            return {"action": "process", "job": data}

        if resp.status_code == 409:
            # Conflict: có thể do trùng dedup key đã xong hoặc đang có worker khác giữ lease còn hạn
            detail = resp.json() if resp.content else {}
            reason = str(detail.get("detail", "Conflict"))
            if "already" in reason.lower() or "succeeded" in reason.lower() or "duplicate" in reason.lower():
                return {"action": "skip_ack", "reason": reason}
            return {"action": "requeue", "reason": reason}

        if resp.status_code == 404:
            return {"action": "skip_ack", "reason": f"Không tìm thấy job {job_id} trong DB"}

        resp.raise_for_status()
        return {"action": "process", "job": resp.json()}

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """Gia hạn lease_expires_at khi worker đang xử lý."""
        url = f"/api/internal/jobs/{job_id}/heartbeat"
        payload = {
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        }
        try:
            resp = self.client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning(f"[API] Heartbeat job {job_id} trả về HTTP {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logger.warning(f"[API] Lỗi gọi heartbeat cho job {job_id}: {e}")
            return False

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        message_id: str,
        result_key: str,
        page_count: int,
        file_size: int,
    ) -> Dict[str, Any]:
        """Báo hoàn thành job (succeeded) kèm dedup key (message_id) và metadata PDF."""
        url = f"/api/internal/jobs/{job_id}/complete"
        payload = {
            "worker_id": worker_id,
            "message_id": message_id,
            "result_key": result_key,
            "page_count": page_count,
            "file_size": file_size,
        }
        resp = self.client.post(url, json=payload)
        if resp.status_code in (200, 409):
            return resp.json() if resp.content else {"status": "succeeded"}
        resp.raise_for_status()
        return {}

    def fail_job(
        self,
        job_id: str,
        worker_id: str,
        message_id: str,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> Dict[str, Any]:
        """Báo lỗi job; API sẽ quyết định retry (queued) hay chốt failed nếu hết attempts."""
        url = f"/api/internal/jobs/{job_id}/fail"
        payload = {
            "worker_id": worker_id,
            "message_id": message_id,
            "error_code": error_code,
            "error_message": error_message[:500],
            "retryable": retryable,
        }
        resp = self.client.post(url, json=payload)
        if resp.status_code in (200, 409):
            return resp.json() if resp.content else {"status": "failed"}
        resp.raise_for_status()
        return {}

    def close(self) -> None:
        self.client.close()