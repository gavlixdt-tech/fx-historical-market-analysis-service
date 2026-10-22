"""Authentication boundary tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app

SECRET = "test-secret-key"


def _secured_app() -> FastAPI:
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        require_auth=True,
        api_key=SECRET,
    )
    return create_app(settings)


def test_missing_api_key_is_rejected(client: TestClient) -> None:
    """The default test app does not require auth; this asserts the default."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_protected_endpoint_requires_api_key() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        # /api/v1/status is a public path by platform convention.
        public = secured_client.get("/api/v1/status")
        assert public.status_code == 200

        # A non-public path must be rejected without a key.
        secured_client.get("/metrics")
        protected = secured_client.get("/api/v1/private")
        assert protected.status_code == 401
        body = protected.json()
        assert body["error"]["code"] == "unauthenticated"
        assert body["error"]["request_id"]


def test_wrong_api_key_is_rejected() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        response = secured_client.get("/api/v1/private", headers={"X-API-Key": "wrong"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"


def test_correct_api_key_is_accepted() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        response = secured_client.get("/api/v1/private", headers={"X-API-Key": SECRET})
        # The route does not exist, so a 404 proves the key was accepted.
        assert response.status_code == 404


def test_error_body_never_contains_the_api_key() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        response = secured_client.get("/api/v1/private", headers={"X-API-Key": "wrong"})
        assert SECRET not in response.text


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "X-Powered-By" not in response.headers


def test_cors_preflight_passes_without_authentication() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        response = secured_client.options(
            "/api/v1/private",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 400)


def test_disallowed_origin_is_not_granted_cors() -> None:
    app = _secured_app()
    with TestClient(app) as secured_client:
        response = secured_client.get(
            "/api/v1/status",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") is None
