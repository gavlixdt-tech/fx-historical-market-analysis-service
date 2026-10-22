"""Correlation ID propagation tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] == response.headers["X-Correlation-ID"]
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]


def test_inbound_correlation_id_is_propagated(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "trace-abc-123"},
    )

    assert response.headers["X-Request-ID"] == "trace-abc-123"
    assert response.json()["meta"]["request_id"] == "trace-abc-123"


def test_correlation_id_header_is_also_accepted(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "corr-xyz-789"},
    )

    assert response.headers["X-Request-ID"] == "corr-xyz-789"


def test_unsafe_characters_are_stripped_from_correlation_id(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "abc<script>"},
    )

    generated = response.headers["X-Request-ID"]
    assert "<" not in generated
    assert ">" not in generated


def test_overlong_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "a" * 500},
    )

    assert len(response.headers["X-Request-ID"]) <= 128


def test_empty_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "---"},
    )

    assert response.headers["X-Request-ID"]
