# Backend image for fx-historical-market-analysis-service.
#
# Multi-stage build: dependencies are installed into a virtual environment in a
# builder stage and only the environment plus application code are copied into
# a slim runtime image. The container runs as a non-root user.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first so that the layer is cached across code changes.
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --upgrade pip && pip install .

COPY backend ./backend

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_MODE=research-simulation

# Run as an unprivileged user.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/backend /app/backend

WORKDIR /app
USER app

ENV PORT=8000
EXPOSE 8000

# The liveness endpoint is used as the container health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
