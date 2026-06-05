FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PHA_HOST=0.0.0.0 \
    PHA_PORT=8787 \
    PYTHONPATH=/app

WORKDIR /app

# Tesseract OCR + Chinese simplified (Apple Health screenshots / lab scans)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY pha ./pha
COPY storage/registry ./storage/registry
COPY storage/schemas ./storage/schemas
COPY scripts/doctor.py scripts/run_selfchecks.sh ./scripts/
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/data /app/storage/users /app/storage/attachments

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PHA_PORT}/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
