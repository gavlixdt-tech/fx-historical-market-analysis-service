"""Integration tests for the health, status and version endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_returns_healthy_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "healthy"
    assert body["data"]["check"] == "liveness"
    assert body["data"]["service"] == "fx-historical-market-analysis-service"
    assert body["data"]["mode"] == "research-simulation"
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["request_id"]
    assert body["meta"]["timestamp_utc"].endswith("Z")
    assert body["errors"] == []


def test_readiness_is_healthy_without_upstream_configured(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "healthy"
    assert body["data"]["check"] == "readiness"
    assert body["data"]["dependencies"][0]["name"] == "fx-market-data-service"
    assert body["data"]["dependencies"][0]["healthy"] is True


def test_version_reports_service_identity(client: TestClient) -> None:
    response = client.get("/api/v1/version")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["service"] == "fx-historical-market-analysis-service"
    assert data["api_version"] == "v1"
    assert data["environment"] == "testing"
    assert data["service_mode"] == "research-simulation"


def test_status_reports_capabilities_and_upstream_state(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["service_id"] == "fx-historical-market-analysis-service"
    assert data["operational_state"] == "operational"
    assert data["uptime_seconds"] >= 0

    # Implemented capabilities must be flagged as implemented.
    implemented = {c["name"]: c["implemented"] for c in data["capabilities"]}
    assert implemented["service_health"] is True
    assert implemented["upstream_integration_contract"] is True
    assert implemented["observability"] is True

    # Analytical capabilities implemented in this phase.
    for implemented_name in (
        "historical_statistics",
        "pattern_discovery",
        "regime_classification",
        "analytical_significance",
        "reproducible_results",
    ):
        assert implemented[implemented_name] is True


def test_status_reports_unconfigured_upstream_truthfully(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    upstream = response.json()["data"]["upstream_integration"]
    assert upstream["service"] == "fx-market-data-service"
    assert upstream["state"] == "unconfigured"
    assert upstream["base_url_configured"] is False
    assert upstream["credential_configured"] is False
    assert upstream["last_checked_at"] is None
    assert upstream["last_check_succeeded"] is None


def test_root_banner_states_foundation_status(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "foundation"
    assert body["mode"] == "research-simulation"
    assert "not implemented" in body["note"].lower()


def test_metrics_endpoint_exposes_prometheus_payload(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "fx_hma_service_up" in response.text


def test_legacy_health_alias(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "research-simulation"


def test_no_analysis_endpoint_is_exposed(client: TestClient) -> None:
    """The analysis engine must not be reachable in this phase."""
    for path in (
        "/api/v1/trading",
        "/api/v1/orders",
    ):
        response = client.get(path)
        assert response.status_code == 404, f"{path} must not exist"


def test_openapi_document_is_generated(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    assert "/api/v1/health/live" in paths
    assert "/api/v1/health/ready" in paths
    assert "/api/v1/status" in paths
    assert "/api/v1/version" in paths
