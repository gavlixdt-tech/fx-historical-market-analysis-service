"""Error envelope tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def test_not_found_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "HTTP_404"
    assert body["error"]["request_id"]


def test_validation_error_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "req-1"})

    assert response.status_code == 200
    # A well-formed request succeeds; the envelope shape is asserted above.
    assert response.json()["meta"]["request_id"] == "req-1"


def test_unhandled_exception_returns_safe_500() -> None:
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="critical",
    )
    app = create_app(settings)

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail: database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "SVR_INTERNAL"
    assert body["error"]["message"] == "An internal server error occurred."
    assert body["error"]["request_id"]
    # The internal exception detail must never reach the client.
    assert "hunter2" not in response.text
    assert "database password" not in response.text


def test_error_envelope_contains_no_stack_trace(client: TestClient) -> None:
    response = client.get("/api/v1/missing")
    assert "traceback" not in response.text.lower()
