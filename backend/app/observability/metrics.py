"""Prometheus-compatible metrics.

A dedicated registry is used so that the exporter never leaks the default
Python process metrics into the service's own metrics endpoint.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "fx_hma_http_requests_total",
    "Total HTTP requests handled by the service.",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "fx_hma_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    registry=REGISTRY,
)

UPSTREAM_REQUESTS_TOTAL = Counter(
    "fx_hma_upstream_requests_total",
    "Total requests made to the upstream market-data service.",
    labelnames=("operation", "outcome"),
    registry=REGISTRY,
)

UPSTREAM_REQUEST_DURATION_SECONDS = Histogram(
    "fx_hma_upstream_request_duration_seconds",
    "Upstream request latency in seconds.",
    labelnames=("operation",),
    registry=REGISTRY,
)

UPSTREAM_LAST_CHECK_SUCCEEDED = Gauge(
    "fx_hma_upstream_last_check_succeeded",
    "1 when the most recent upstream connectivity check succeeded, 0 otherwise.",
    registry=REGISTRY,
)

SERVICE_UP = Gauge(
    "fx_hma_service_up",
    "1 when the service process is running.",
    registry=REGISTRY,
)


def metrics_response() -> tuple[bytes, str]:
    """Render the current metrics in the Prometheus text exposition format."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
