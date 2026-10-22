"""Structured JSON logging configuration.

Logs are emitted as one JSON object per line so that a log shipper can parse
them without a custom regex. A correlation ID is attached to every record
emitted while handling a request.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from backend.app.core.config import Settings

# Reserved LogRecord attributes that must not be overwritten by `extra`.
_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

        # Promote any structured `extra` fields onto the payload.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_") or key in payload:
                continue
            if key == "request_id":
                payload["request_id"] = value
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter used for local development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None)
        prefix = f"[{request_id}] " if request_id else ""
        base = f"{record.levelname:<8} {record.name}: {prefix}{record.getMessage()}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging(settings: Settings) -> None:
    """Configure the root logger from validated settings.

    Replaces any existing handlers so that repeated application-factory calls
    (for example in tests) do not stack duplicate handlers.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Third-party loggers are noisy at INFO level.
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
