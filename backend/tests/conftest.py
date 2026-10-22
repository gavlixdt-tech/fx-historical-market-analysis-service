"""Shared pytest fixtures.

Tests build their own application instance through the factory so that no
global state is shared between test modules.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Return test settings with authentication disabled by default."""
    return Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        require_auth=False,
        upstream_market_data_base_url=None,
        upstream_api_key=None,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Return a freshly built application instance."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Return a TestClient bound to the application under test."""
    with TestClient(app) as test_client:
        yield test_client
