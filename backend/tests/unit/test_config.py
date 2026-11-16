"""Configuration validation tests."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.app.core.config import Settings

TRUSTED_HISTORICAL_KEY = base64.b64encode(b"k" * 32).decode("ascii")
TRUSTED_HISTORICAL_KEYS_JSON = '{"service1-key":"' + TRUSTED_HISTORICAL_KEY + '"}'


def test_defaults_are_safe_for_development() -> None:
    settings = Settings()
    assert settings.service_name == "fx-historical-market-analysis-service"
    assert settings.service_mode == "research-simulation"
    assert settings.enable_live_trading is False
    assert settings.api_prefix == "/api/v1"


def test_service_and_upstream_credentials_are_hidden_from_repr() -> None:
    settings = Settings(
        api_key="service-two-api-secret-value",
        upstream_api_key="market-data-upstream-secret-value",
    )

    rendered = repr(settings)

    assert "service-two-api-secret-value" not in rendered
    assert "market-data-upstream-secret-value" not in rendered


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
            api_key="x" * 32,
            cors_allow_origins="*",
        )


def test_production_accepts_explicit_configuration() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="x" * 32,
        cors_allow_origins="https://dashboard.internal",
    )
    assert settings.is_production is True
    assert settings.cors_origin_list == ["https://dashboard.internal"]


def test_production_requires_upstream_credential_when_configured() -> None:
    with pytest.raises(PydanticValidationError, match="upstream_api_key"):
        Settings(
            environment="production",
            require_auth=True,
            api_key="x" * 32,
            upstream_market_data_base_url="https://market-data.internal",
        )


def test_production_accepts_authenticated_railway_private_http_upstream() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="x" * 32,
        upstream_market_data_base_url=("http://fx-market-data-service.railway.internal:8000"),
        upstream_api_key="market-data-service-key",
        upstream_historical_attestation_public_keys_json=TRUSTED_HISTORICAL_KEYS_JSON,
        upstream_historical_attestation_required=True,
    )

    assert settings.upstream_configured is True


def test_production_rejects_plain_http_public_upstream() -> None:
    with pytest.raises(PydanticValidationError, match="must use https"):
        Settings(
            environment="production",
            require_auth=True,
            api_key="x" * 32,
            upstream_market_data_base_url="http://market-data.example.com:8000",
            upstream_api_key="market-data-service-key",
        )


def test_production_rejects_railway_private_http_without_explicit_port() -> None:
    with pytest.raises(PydanticValidationError, match="must use https"):
        Settings(
            environment="production",
            require_auth=True,
            api_key="x" * 32,
            upstream_market_data_base_url="http://fx-market-data-service.railway.internal",
            upstream_api_key="market-data-service-key",
        )


def test_production_accepts_authenticated_upstream_configuration() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="x" * 32,
        upstream_market_data_base_url="https://market-data.internal",
        upstream_api_key="market-data-service-key",
        upstream_historical_attestation_public_keys_json=TRUSTED_HISTORICAL_KEYS_JSON,
        upstream_historical_attestation_required=True,
    )
    assert settings.upstream_configured is True


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


def test_market_data_replay_requires_explicit_publication_lag() -> None:
    settings = Settings()
    assert settings.upstream_replay_availability_delay_seconds is None
    empty_setting = Settings(upstream_replay_availability_delay_seconds="")
    assert empty_setting.upstream_replay_availability_delay_seconds is None


def test_market_data_replay_publication_lag_is_bounded() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(upstream_replay_availability_delay_seconds=86_401)


def test_trusted_hosts_are_parsed() -> None:
    settings = Settings(trusted_hosts="localhost, testserver ,127.0.0.1")
    assert settings.trusted_host_list == ["localhost", "testserver", "127.0.0.1"]


def test_production_requires_historical_attestation_trust_bundle() -> None:
    with pytest.raises(PydanticValidationError, match="historical replay requires"):
        Settings(
            environment="production",
            require_auth=True,
            api_key="x" * 32,
            upstream_market_data_base_url="https://market-data.internal",
            upstream_api_key="market-data-service-key",
        )


def test_historical_attestation_public_keys_must_be_raw_ed25519_keys() -> None:
    with pytest.raises(PydanticValidationError, match="exactly 32 bytes"):
        Settings(
            upstream_historical_attestation_public_keys_json='{"service1-key":"'
            + base64.b64encode(b"short").decode("ascii")
            + '"}'
        )


def test_central_replay_settings_require_all_service_credentials() -> None:
    with pytest.raises(PydanticValidationError, match="central replay settings require"):
        Settings(gfx_settings_enabled=True, gfx_settings_required=True)


def test_central_replay_settings_accept_valid_origins_and_workload_identity() -> None:
    settings = Settings(
        gfx_settings_enabled=True,
        gfx_settings_required=True,
        gfx_settings_service_url="https://admin.example",
        fx_security_service_url="https://security.example",
        gfx_settings_client_id="service-two-client-123",
        gfx_settings_client_secret="s" * 48,
    )
    assert settings.gfx_settings_enabled is True
    assert settings.gfx_settings_required is True
    assert "s" * 48 not in repr(settings)


def test_central_replay_settings_required_cannot_be_disabled() -> None:
    with pytest.raises(PydanticValidationError, match="GFX_SETTINGS_REQUIRED=true"):
        Settings(gfx_settings_required=True, gfx_settings_enabled=False)


def test_production_central_replay_settings_require_secure_origins() -> None:
    with pytest.raises(PydanticValidationError, match="must use HTTPS"):
        Settings(
            environment="production",
            gfx_settings_enabled=True,
            gfx_settings_required=True,
            gfx_settings_service_url="http://admin.example",
            fx_security_service_url="https://security.example",
            gfx_settings_client_id="service-two-client-123",
            gfx_settings_client_secret="s" * 48,
        )


def test_production_central_replay_settings_allow_railway_private_origins() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="x" * 32,
        gfx_settings_enabled=True,
        gfx_settings_required=True,
        gfx_settings_service_url="http://fx-admin-console.railway.internal:8000",
        fx_security_service_url="http://fx-security-access-service.railway.internal:8000",
        gfx_settings_client_id="service-two-client-123",
        gfx_settings_client_secret="s" * 48,
    )
    assert settings.gfx_settings_enabled is True


def test_blank_optional_central_settings_credentials_are_allowed_when_disabled() -> None:
    settings = Settings(
        gfx_settings_enabled=False,
        gfx_settings_required=False,
        gfx_settings_client_id="",
        gfx_settings_client_secret="",
    )
    assert settings.gfx_settings_enabled is False
    assert settings.gfx_settings_client_id == ""
    assert settings.gfx_settings_client_secret == ""


def test_short_central_settings_credentials_are_rejected_when_enabled() -> None:
    with pytest.raises(PydanticValidationError, match="GFX_SETTINGS_CLIENT_ID must contain"):
        Settings(
            gfx_settings_enabled=True,
            gfx_settings_required=True,
            gfx_settings_service_url="https://admin.example",
            fx_security_service_url="https://security.example",
            gfx_settings_client_id="short",
            gfx_settings_client_secret="s" * 48,
        )
