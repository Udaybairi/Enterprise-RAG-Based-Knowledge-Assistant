# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt requirements-local.txt ./
RUN pip install -r requirements-local.txt
# Optional: pre-fetch the tokenizer used for chunk sizing (falls back to a heuristic when unavailable).
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || echo "tiktoken encoding not prefetched"

COPY app ./app

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data /opt/tiktoken \
    && chown -R appuser /data /opt/tiktoken
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
