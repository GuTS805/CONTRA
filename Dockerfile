# CONTRA has no third-party Python dependencies.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTRA_HOST=0.0.0.0 \
    CONTRA_PUBLIC=1 \
    CONTRA_DB=/data/contra.sqlite3

WORKDIR /app
COPY contra ./contra
COPY web ./web
COPY data/fixtures ./data/fixtures

RUN useradd --create-home --uid 10001 contra && mkdir -p /data && chown contra /data
USER contra

EXPOSE 8000
CMD ["python", "-m", "contra.server"]
