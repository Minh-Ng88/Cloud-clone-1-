import os
import json
import time
import logging
from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger("worker.queue")


class QueueMessage:
    def __init__(self, body: Dict[str, Any], message_id: str, raw_handle: Any):
        self.body = body
        self.message_id = message_id
        self.raw_handle = raw_handle


class QueueAdapter(ABC):
    @abstractmethod
    def consume(self, callback: Callable[[QueueMessage], None]) -> None:
        pass

    @abstractmethod
    def ack(self, msg: QueueMessage) -> None:
        pass

    @abstractmethod
    def nack(self, msg: QueueMessage, requeue: bool = True) -> None:
        pass

    @abstractmethod
    def dead_letter(self, msg: QueueMessage, reason: str = "") -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class RabbitMQAdapter(QueueAdapter):
    def __init__(self, amqp_url: str, queue_name: str):
        import pika
        self.pika = pika
        self.amqp_url = amqp_url
        self.queue_name = queue_name
        self.dlq_name = f"{queue_name}.dlq"
        self.connection = None
        self.channel = None

    def _connect(self):
        params = self.pika.URLParameters(self.amqp_url)
        params.heartbeat = 60
        params.blocked_connection_timeout = 300
        self.connection = self.pika.BlockingConnection(params)
        self.channel = self.connection.channel()

        # Khai báo Dead Letter Queue và Main Queue
        self.channel.queue_declare(queue=self.dlq_name, durable=True)
        self.channel.queue_declare(
            queue=self.queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.dlq_name,
            },
        )
        self.channel.basic_qos(prefetch_count=1)

    def consume(self, callback: Callable[[QueueMessage], None]) -> None:
        while True:
            try:
                if not self.connection or self.connection.is_closed:
                    self._connect()
                    logger.info(f"[RabbitMQ] Đã kết nối tới queue '{self.queue_name}'")

                def _on_message(ch, method, properties, body_bytes):
                    try:
                        payload = json.loads(body_bytes.decode("utf-8"))
                    except Exception as e:
                        logger.error(f"[RabbitMQ] Lỗi parse JSON message: {e} -> đẩy vào DLQ")
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                        return

                    msg_id = (
                        getattr(properties, "message_id", None)
                        or payload.get("message_id")
                        or str(method.delivery_tag)
                    )
                    handle = {"channel": ch, "delivery_tag": method.delivery_tag}
                    callback(QueueMessage(body=payload, message_id=str(msg_id), raw_handle=handle))

                self.channel.basic_consume(
                    queue=self.queue_name,
                    on_message_callback=_on_message,
                    auto_ack=False,
                )
                self.channel.start_consuming()
            except KeyboardInterrupt:
                logger.info("[RabbitMQ] Dừng consumer theo tín hiệu ngắt.")
                self.close()
                break
            except Exception as e:
                logger.warning(f"[RabbitMQ] Mất kết nối ({e}), thử kết nối lại sau 5s...")
                time.sleep(5)

    def ack(self, msg: QueueMessage) -> None:
        ch = msg.raw_handle["channel"]
        tag = msg.raw_handle["delivery_tag"]
        if ch.is_open:
            ch.basic_ack(delivery_tag=tag)

    def nack(self, msg: QueueMessage, requeue: bool = True) -> None:
        ch = msg.raw_handle["channel"]
        tag = msg.raw_handle["delivery_tag"]
        if ch.is_open:
            ch.basic_nack(delivery_tag=tag, requeue=requeue)

    def dead_letter(self, msg: QueueMessage, reason: str = "") -> None:
        logger.warning(f"[RabbitMQ] Dead-letter message {msg.message_id}: {reason}")
        self.nack(msg, requeue=False)

    def close(self) -> None:
        try:
            if self.channel and self.channel.is_open:
                self.channel.close()
            if self.connection and self.connection.is_open:
                self.connection.close()
        except Exception:
            pass


class AzureServiceBusAdapter(QueueAdapter):
    def __init__(self, conn_str: str, queue_name: str):
        from azure.servicebus import ServiceBusClient
        self.ServiceBusClient = ServiceBusClient
        self.conn_str = conn_str
        self.queue_name = queue_name
        self.client = self.ServiceBusClient.from_connection_string(conn_str=self.conn_str)
        self.receiver = self.client.get_queue_receiver(queue_name=self.queue_name)

    def consume(self, callback: Callable[[QueueMessage], None]) -> None:
        logger.info(f"[AzureServiceBus] Đang lắng nghe queue '{self.queue_name}'")
        with self.receiver:
            while True:
                try:
                    messages = self.receiver.receive_messages(max_message_count=1, max_wait_time=5)
                    for sb_msg in messages:
                        raw_str = "".join(
                            b.decode("utf-8") if isinstance(b, bytes) else str(b)
                            for b in sb_msg.body
                        )
                        try:
                            payload = json.loads(raw_str)
                        except Exception as e:
                            logger.error(f"[AzureServiceBus] Lỗi parse JSON: {e} -> dead-letter")
                            self.receiver.dead_letter_message(
                                sb_msg, reason="InvalidJSON", error_description=str(e)
                            )
                            continue

                        msg_id = (
                            sb_msg.message_id
                            or payload.get("message_id")
                            or str(sb_msg.sequence_number)
                        )
                        callback(QueueMessage(body=payload, message_id=str(msg_id), raw_handle=sb_msg))
                except KeyboardInterrupt:
                    logger.info("[AzureServiceBus] Dừng consumer.")
                    self.close()
                    break
                except Exception as e:
                    logger.warning(f"[AzureServiceBus] Lỗi nhận message ({e}), thử lại sau 5s...")
                    time.sleep(5)

    def ack(self, msg: QueueMessage) -> None:
        self.receiver.complete_message(msg.raw_handle)

    def nack(self, msg: QueueMessage, requeue: bool = True) -> None:
        if requeue:
            self.receiver.abandon_message(msg.raw_handle)
        else:
            self.dead_letter(msg, reason="RejectedWithoutRequeue")

    def dead_letter(self, msg: QueueMessage, reason: str = "") -> None:
        logger.warning(f"[AzureServiceBus] Dead-letter message {msg.message_id}: {reason}")
        self.receiver.dead_letter_message(
            msg.raw_handle, reason="WorkerFailed", error_description=reason[:256]
        )

    def close(self) -> None:
        try:
            self.receiver.close()
            self.client.close()
        except Exception:
            pass


def create_queue_adapter() -> QueueAdapter:
    provider = os.getenv("QUEUE_PROVIDER", "rabbitmq").strip().lower()
    queue_name = os.getenv("QUEUE_NAME", "doc2pdf.jobs")

    if provider in ("azure", "servicebus", "azure_servicebus"):
        conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING", "")
        if not conn_str:
            raise ValueError("Thiếu biến môi trường AZURE_SERVICEBUS_CONNECTION_STRING")
        return AzureServiceBusAdapter(conn_str=conn_str, queue_name=queue_name)

    amqp_url = os.getenv("RABBITMQ_URL", "amqp://doc2pdf:doc2pdf_dev_password@localhost:5672/")
    return RabbitMQAdapter(amqp_url=amqp_url, queue_name=queue_name)