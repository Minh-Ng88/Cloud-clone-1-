# Đích mặc định (stage cuối) = runtime. Chạy test: docker compose --profile test run --rm api-test
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests ./tests
CMD ["pytest", "-q", "tests"]

FROM base AS runtime
RUN useradd --system --no-create-home appuser
USER appuser
EXPOSE 8000
# Chạy migration rồi mới khởi động API
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
