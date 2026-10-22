"""Request size limit and trusted host tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def _app_with_limit(limit: int) -> FastAPI:
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        max_request_body_bytes=limit,
    )
    return create_app(settings)


def test_oversized_body_is_rejected() -> None:
    app = _app_with_limit(2048)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/anything",
            content=b"x" * 4096,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "VAL_REQUEST_TOO_LARGE"


def test_small_body_is_not_rejected_by_the_limit() -> None:
    app = _app_with_limit(65536)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/anything",
            content=b"x" * 16,
            headers={"Content-Type": "application/octet-stream"},
        )
        # 404 proves the request passed the size gate.
        assert response.status_code == 404


def test_untrusted_host_is_rejected() -> None:
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        trusted_hosts="localhost",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"Host": "evil.example.com"})
        assert response.status_code == 400


def test_trusted_host_is_accepted() -> None:
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        trusted_hosts="localhost",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"Host": "localhost"})
        assert response.status_code == 200
