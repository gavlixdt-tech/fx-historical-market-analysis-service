"""OpenTelemetry-compatible tracing instrumentation.

Tracing is opt-in: it is only enabled when `OTEL_ENABLED` is true and an
OTLP endpoint is configured. When disabled, the service still creates spans
through the OpenTelemetry API, but they are no-ops, so instrumented code does
not need to branch on whether tracing is active.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from backend.app.core.config import Settings

logger = logging.getLogger("fx-historical-market-analysis-service.tracing")


def init_observability(settings: Settings, app: FastAPI) -> None:
    """Configure OpenTelemetry tracing for the application.

    The OTLP exporter is only used when both `otel_enabled` and
    `otel_endpoint` are set. Instrumentation failures are logged and ignored
    so that an unavailable collector can never prevent the service from
    starting.
    """
    if not settings.otel_enabled:
        logger.info("tracing_disabled")
        return

    if not settings.otel_endpoint:
        logger.warning("tracing_disabled_missing_endpoint")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
                "service.namespace": "fx-ai-platform",
                "deployment.environment": settings.environment,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        logger.info("tracing_enabled", extra={"endpoint": settings.otel_endpoint})
    except Exception as exc:  # pragma: no cover - depends on collector availability
        logger.warning("tracing_initialisation_failed", extra={"reason": type(exc).__name__})
