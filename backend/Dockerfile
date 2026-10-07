# Контекст сборки — корень репозитория (нужны database/migrations)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    OMP_THREAD_LIMIT=1

# tesseract (rus+eng) — OCR сканов; libreoffice-writer — docx/doc/rtf -> pdf;
# unar — распаковка RAR; шрифты с кириллицей.
# OMP_THREAD_LIMIT=1: процессы tesseract идут параллельно, внутренние потоки OpenMP им только мешают
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
        libreoffice-writer-nogui \
        unar \
        fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/pytest.ini .
COPY database/migrations ./migrations

RUN useradd --create-home --uid 1000 app && mkdir -p /data/storage && chown -R app:app /data /app
USER app

ENV STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
