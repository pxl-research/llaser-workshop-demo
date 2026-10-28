# LLASER workshop backend. Build context: AI/AI
#   docker build -t llaser-workshop/backend:local AI/AI
# bookworm builder: same glibc (2.36) as the distroless Debian 12 runtime, so no wheel can need a newer one.
FROM python:3.11-slim-bookworm AS builder
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --only-binary :all: --require-hashes --prefix=/install -r /tmp/requirements.txt \
 && mkdir -p /seed/data

FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app
COPY --from=builder /install /usr/local
# Owned by nonroot, so a new named volume mounted here starts out writable.
COPY --from=builder --chown=nonroot:nonroot /seed/data /app/data
COPY __init__.py /app/AI/
COPY API /app/AI/API
COPY Chunking /app/AI/Chunking
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/usr/local/lib/python3.11/site-packages \
    ANONYMIZED_TELEMETRY=False
USER nonroot
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD ["/usr/bin/python3.11", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]
ENTRYPOINT ["/usr/bin/python3.11"]
CMD ["-u", "-m", "uvicorn", "AI.API.API:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--log-level", "info"]
