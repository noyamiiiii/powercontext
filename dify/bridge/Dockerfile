FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORY_MEMORY_HOST=0.0.0.0 \
    STORY_MEMORY_PORT=8766 \
    STORY_MEMORY_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 bridge \
    && mkdir -p /data \
    && chown -R bridge:bridge /data

USER bridge

EXPOSE 8766
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=2)"

CMD ["dify-memory-bridge"]
