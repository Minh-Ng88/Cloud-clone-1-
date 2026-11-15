"""Kiểm tra file thật bằng nội dung (magic bytes), không tin đuôi file hay Content-Type."""
from app.errors import ApiError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
_LABEL = {"png": "PNG", "jpg": "JPEG", "txt": "văn bản UTF-8", "md": "văn bản UTF-8"}


def _reject(fmt: str, reason: str) -> ApiError:
    return ApiError(422, "INVALID_FILE", f"Nội dung file không phải {_LABEL[fmt]} hợp lệ",
                    {"expected_format": fmt, "reason": reason})


def validate_content(fmt: str, data: bytes) -> None:
    """Ném ApiError(422, INVALID_FILE) nếu nội dung không khớp định dạng khai báo qua đuôi file."""
    if fmt == "png":
        if not data.startswith(PNG_MAGIC):
            raise _reject(fmt, "sai magic bytes")
    elif fmt == "jpg":
        if not data.startswith(JPEG_MAGIC):
            raise _reject(fmt, "sai magic bytes")
    else:  # txt, md
        if b"\x00" in data:
            raise _reject(fmt, "chứa byte NUL (file nhị phân)")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise _reject(fmt, "không phải UTF-8")
