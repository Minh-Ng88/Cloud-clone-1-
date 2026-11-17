import os
import logging
from typing import Optional
import boto3
from botocore.client import Config

logger = logging.getLogger("worker.s3")


class S3StorageClient:
    """Client tải file nguồn và upload file PDF kết quả lên SeaweedFS / MinIO / AWS S3."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        sources_bucket: Optional[str] = None,
        results_bucket: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT", "http://localhost:8333")
        self.access_key = access_key or os.getenv("S3_ACCESS_KEY", "any")
        self.secret_key = secret_key or os.getenv("S3_SECRET_KEY", "any")
        self.sources_bucket = sources_bucket or os.getenv("S3_BUCKET_SOURCES", "sources")
        self.results_bucket = results_bucket or os.getenv("S3_BUCKET_RESULTS", "results")

        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(signature_version="s3v4"),
            region_name=os.getenv("S3_REGION", "us-east-1"),
        )

    def ensure_buckets(self) -> None:
        for bucket in (self.sources_bucket, self.results_bucket):
            try:
                self.client.head_bucket(Bucket=bucket)
            except Exception:
                try:
                    self.client.create_bucket(Bucket=bucket)
                    logger.info(f"[S3] Đã tạo bucket '{bucket}'")
                except Exception as e:
                    logger.warning(f"[S3] Không thể tạo bucket '{bucket}': {e}")

    def download_source(self, object_key: str, local_path: str, bucket: Optional[str] = None) -> str:
        target_bucket = bucket or self.sources_bucket
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        logger.info(f"[S3] Tải s3://{target_bucket}/{object_key} -> {local_path}")
        self.client.download_file(target_bucket, object_key, local_path)
        return local_path

    def upload_result(self, local_path: str, object_key: str, bucket: Optional[str] = None) -> str:
        target_bucket = bucket or self.results_bucket
        logger.info(f"[S3] Upload {local_path} -> s3://{target_bucket}/{object_key}")
        self.client.upload_file(
            local_path,
            target_bucket,
            object_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        return object_key