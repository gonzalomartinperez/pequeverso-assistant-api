# syntax=docker/dockerfile:1
# Pequeverso assistant API. One process, one uvicorn worker (in-process run registry and a single
# SQLite writer; see docs/deployment-contract.md). Persistent state lives in /data.
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv

FROM python:3.13-slim@sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim@sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024 AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/assistant.sqlite3
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY migrations ./migrations
COPY catalog ./catalog
# Runtime installs nothing; remove the global installer and its unused vendored dependencies.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && mkdir -p /data && chown 65532:65532 /data
# Keep revision metadata after filesystem layers so a new revision reuses dependencies.
ARG SERVICE_REVISION=
ENV SERVICE_REVISION=${SERVICE_REVISION}
USER 65532:65532
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-proxy-headers", "--no-access-log", "--no-server-header", \
     "--timeout-graceful-shutdown", "15", "--timeout-keep-alive", "5", "--limit-concurrency", "200"]
