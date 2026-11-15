import logging

from app.errors import request_id_var


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s: %(message)s"))
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
