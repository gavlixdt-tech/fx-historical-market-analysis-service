"""Configuration validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.app.core.config import Settings


def test_defaults_are_safe_for_development() -> None:
    settings = Settings()
    assert settings.service_name == "fx-historical-market-analysis-service"
    assert settings.service_mode == "research-simulation"
    assert settings.enable_live_trading is False
    assert settings.api_prefix == "/api/v1"


def test_require_auth_requires_api_key() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(require_auth=True, api_key=None)


def test_live_trading_cannot_be_enabled() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(enable_live_trading=True)


def test_production_requires_authentication() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(environment="production", require_auth=False)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            environment="production",
            require_auth=True,
            api_key="secret",
            cors_allow_origins="*",
        )


def test_production_accepts_explicit_configuration() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="secret",
        cors_allow_origins="https://dashboard.internal",
    )
    assert settings.is_production is True
    assert settings.cors_origin_list == ["https://dashboard.internal"]


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(environment="staging")


def test_invalid_log_format_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(log_format="xml")


def test_service_mode_must_be_research_simulation() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(service_mode="live")


def test_upstream_base_url_must_be_http() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(upstream_market_data_base_url="ftp://example.invalid")


def test_upstream_base_url_is_normalised() -> None:
    settings = Settings(upstream_market_data_base_url="https://upstream.internal/")
    assert settings.upstream_market_data_base_url == "https://upstream.internal"
    assert settings.upstream_configured is True


def test_empty_upstream_base_url_means_unconfigured() -> None:
    settings = Settings(upstream_market_data_base_url="")
    assert settings.upstream_configured is False


def test_trusted_hosts_are_parsed() -> None:
    settings = Settings(trusted_hosts="localhost, testserver ,127.0.0.1")
    assert settings.trusted_host_list == ["localhost", "testserver", "127.0.0.1"]
