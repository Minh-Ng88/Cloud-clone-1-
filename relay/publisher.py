"""Adapter hàng đợi (RabbitMQ). Đổi sang SQS / Pub/Sub / Service Bus = viết lớp mới cùng giao diện:
    connect(), closed, publish(message_id, payload), wait(seconds)
"""
import json

import pika
from pika.exceptions import UnroutableError

# Tên topology — phải khớp docs/contract.md
EXCHANGE = "doc2pdf.jobs"
ROUTING_KEY = "job.convert"
QUEUE = "doc2pdf.convert"
DLX = "doc2pdf.dlx"
DEAD_KEY = "job.convert.dead"
DEAD_QUEUE = "doc2pdf.convert.dead"

# event_type (payload["type"]) -> (exchange, routing key)
ROUTES = {"job.convert.requested": (EXCHANGE, ROUTING_KEY)}


class PermanentPublishError(Exception):
    """Sự kiện không thể gửi dù thử lại (type lạ, không định tuyến được)."""


class RabbitPublisher:
    def __init__(self, url: str) -> None:
        self.url = url
        self.conn = None
        self.ch = None

    @property
    def closed(self) -> bool:
        return self.conn is None or self.conn.is_closed

    def connect(self) -> None:
        self.conn = pika.BlockingConnection(pika.URLParameters(self.url))
        self.ch = self.conn.channel()
        self.ch.confirm_delivery()
        self._declare_topology()

    def _declare_topology(self) -> None:
        ch = self.ch
        ch.exchange_declare(EXCHANGE, exchange_type="direct", durable=True)
        ch.exchange_declare(DLX, exchange_type="direct", durable=True)
        ch.queue_declare(DEAD_QUEUE, durable=True)
        ch.queue_bind(DEAD_QUEUE, DLX, DEAD_KEY)
        ch.queue_declare(QUEUE, durable=True, arguments={
            "x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": DEAD_KEY})
        ch.queue_bind(QUEUE, EXCHANGE, ROUTING_KEY)

    def publish(self, message_id: str, payload: dict) -> None:
        route = ROUTES.get(payload.get("type"))
        if route is None:
            raise PermanentPublishError(f"unknown event type: {payload.get('type')}")
        props = pika.BasicProperties(
            message_id=message_id, content_type="application/json", delivery_mode=2,
            type=payload["type"],
            headers={"x-schema-version": payload.get("schema_version", 1),
                     "x-request-id": payload.get("request_id")})
        try:
            self.ch.basic_publish(route[0], route[1], json.dumps(payload).encode(), props,
                                  mandatory=True)  # confirm: lỗi/nack sẽ ném ngoại lệ AMQPError
        except UnroutableError as e:
            raise PermanentPublishError(f"unroutable: {e}") from e

    def wait(self, seconds: float) -> None:
        self.conn.process_data_events(time_limit=seconds)  # nghỉ nhưng vẫn giữ heartbeat
