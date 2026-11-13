"""Application configuration loaded from validated environment variables.

Uses Pydantic Settings for environment-variable parsing and validation.
Fails fast on invalid mandatory configuration. Never embeds credentials.

Configuration is validated at startup so that a misconfigured deployment
refuses to start rather than serving traffic with unsafe defaults.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration.

    All values are sourced from environment variables (or a .env file in local
    development). Production values must never be committed to version control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Service identity ----
    service_name: str = Field(
        default="fx-historical-market-analysis-service",
        description="Service identifier",
    )
    service_version: str = Field(default="0.1.0", description="Application version")
    api_version: str = Field(default="v1", description="API version prefix")
    environment: str = Field(default="development", description="Deployment environment")
    service_mode: str = Field(default="research-simulation", description="Operating mode")

    # ---- Runtime ----
    api_host: str = Field(default="0.0.0.0", description="Bind host")  # noqa: S104
    api_port: int = Field(default=8000, description="Bind port", ge=1, le=65535)
    log_level: str = Field(default="info", description="Log level")
    log_format: str = Field(default="json", description="Log format: json or console")

    # ---- Security ----
    enable_live_trading: bool = Field(
        default=False,
        description="Live trading must remain disabled - this service is research only",
    )
    cors_allow_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated CORS allowlist",
    )
    cors_allow_credentials: bool = Field(default=True, description="CORS allow credentials")
    cors_allow_methods: str = Field(
        default="GET,POST,PUT,DELETE,OPTIONS",
        description="CORS allow methods",
    )
    cors_allow_headers: str = Field(
        default="Content-Type,Authorization,X-Request-ID,X-Correlation-ID,X-API-Key",
        description="CORS allow headers",
    )
    trusted_hosts: str = Field(
        default="localhost,127.0.0.1,testserver",
        description="Trusted proxy/host allowlist (testserver is FastAPI TestClient)",
    )
    docs_enabled_in_production: bool = Field(
        default=False,
        description="Enable OpenAPI docs in production",
    )

    # ---- Authentication (inbound) ----
    require_auth: bool = Field(
        default=False,
        description="Require API key authentication on all non-public endpoints",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authenticating inbound requests (server-side only)",
        repr=False,
    )

    # ---- Request limits ----
    max_request_body_bytes: int = Field(
        default=1_048_576,
        description="Maximum accepted request body size in bytes",
        ge=1024,
        le=33_554_432,
    )

    # ---- Forecasting research artifacts ----
    forecasting_artifact_dir: str | None = Field(
        default=None,
        description="Optional local directory for reproducible experiment artifact JSON (no DB)",
    )

    # ---- Upstream integration: fx-market-data-service ----
    # The upstream base URL is configurable; no production hostname is hard-coded.
    upstream_market_data_base_url: str | None = Field(
        default=None,
        description="Base URL of the upstream market-data service (server-side only)",
    )
    upstream_api_key: str | None = Field(
        default=None,
        description="Credential presented to the upstream service (server-side only)",
        repr=False,
    )

    # ---- Upstream integration: fx-feature-engineering-service ----
    upstream_feature_engineering_base_url: str | None = Field(
        default=None,
        description="Base URL of the feature-engineering service (server-side only)",
    )
    upstream_feature_engineering_auth_token: str | None = Field(
        default=None,
        description="Bearer token for the feature-engineering session-context API",
        repr=False,
    )
    upstream_timeout_seconds: float = Field(
        default=5.0,
        description="Overall upstream request timeout in seconds",
        ge=0.5,
        le=60.0,
    )
    upstream_connect_timeout_seconds: float = Field(
        default=5.0,
        description="Upstream connection timeout in seconds",
        ge=0.5,
        le=60.0,
    )
    upstream_read_timeout_seconds: float = Field(
        default=5.0,
        description="Upstream read timeout in seconds",
        ge=0.5,
        le=60.0,
    )
    upstream_max_retries: int = Field(
        default=2,
        description="Maximum retries for transient upstream failures",
        ge=0,
        le=5,
    )
    upstream_retry_max_duration_seconds: float = Field(
        default=10.0,
        description="Maximum total duration for upstream retry attempts",
        ge=1.0,
        le=60.0,
    )
    upstream_max_concurrent_requests: int = Field(
        default=4,
        description="Maximum concurrent requests to the historical market-data service",
        ge=1,
        le=32,
    )
    upstream_max_response_bytes: int = Field(
        default=16_777_216,
        description="Maximum decompressed response size accepted from the market-data service",
        ge=1024,
        le=67_108_864,
    )
    upstream_connectivity_check_enabled: bool = Field(
        default=True,
        description="Allow the readiness probe to perform a live upstream check",
    )
    upstream_replay_availability_delay_seconds: int | None = Field(
        default=None,
        description=(
            "Required publication-lag assumption for provider candles without "
            "point-in-time availability timestamps"
        ),
        ge=1,
        le=86_400,
    )
    upstream_max_history_limit: int = Field(
        default=5000,
        description="Maximum permitted historical request limit",
        ge=1,
        le=5000,
    )
    upstream_allowed_history_start: datetime | None = Field(
        default=None,
        description="Earliest permitted historical request start (ISO-8601 UTC)",
    )
    upstream_allowed_history_end: datetime | None = Field(
        default=None,
        description="Latest permitted historical request end (ISO-8601 UTC)",
    )

    # ---- Observability ----
    otel_enabled: bool = Field(default=False, description="Enable OpenTelemetry export")
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP HTTP endpoint for trace export (e.g. http://otel-collector:4318)",
    )
    metrics_enabled: bool = Field(default=True, description="Expose Prometheus metrics")

    # ---- Persistence ----
    # No database is provisioned. The field is reserved for a future,
    # separately approved persistence integration.
    database_url: str | None = Field(
        default=None, description="Database connection string (unused)"
    )

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        allowed = {"development", "testing", "production", "research-simulation"}
        if value not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return value

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, value: str) -> str:
        if value not in {"json", "console"}:
            raise ValueError("log_format must be 'json' or 'console'")
        return value

    @field_validator("upstream_replay_availability_delay_seconds", mode="before")
    @classmethod
    def _empty_replay_availability_delay_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("service_mode")
    @classmethod
    def _validate_service_mode(cls, value: str) -> str:
        if value != "research-simulation":
            raise ValueError("service_mode must be 'research-simulation' for this scaffold phase")
        return value

    @field_validator("upstream_feature_engineering_base_url")
    @classmethod
    def _validate_feature_engineering_base_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            raise ValueError(
                "upstream_feature_engineering_base_url must be an http(s) origin"
            )
        if (
            parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "upstream_feature_engineering_base_url must be an origin without "
                "credentials, path, query, or fragment"
            )
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(
                "upstream_feature_engineering_base_url contains an invalid port"
            ) from exc
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))

    @field_validator("upstream_market_data_base_url")
    @classmethod
    def _validate_upstream_base_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            raise ValueError("upstream_market_data_base_url must be an http(s) origin")
        if parsed.username or parsed.password:
            raise ValueError("upstream_market_data_base_url must not contain credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError(
                "upstream_market_data_base_url must be an origin without path, query, or fragment"
            )
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("upstream_market_data_base_url contains an invalid port") from exc
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))

    @model_validator(mode="after")
    def _validate_security_invariants(self) -> Settings:
        if self.require_auth and not self.api_key:
            raise ValueError("api_key must be set when require_auth is true")
        if self.enable_live_trading:
            raise ValueError(
                "ENABLE_LIVE_TRADING must be false - this service is research/simulation only"
            )
        if self.is_production:
            if "*" in self.cors_origin_list:
                raise ValueError("Wildcard CORS origin is not permitted in production")
            if not self.require_auth:
                raise ValueError("require_auth must be true in production")
            if self.api_key is None or len(self.api_key) < 32:
                raise ValueError("api_key must contain at least 32 characters in production")
            if self.upstream_market_data_base_url:
                upstream = urlsplit(self.upstream_market_data_base_url)
                private_railway_http = (
                    upstream.scheme == "http"
                    and upstream.hostname is not None
                    and upstream.hostname.endswith(".railway.internal")
                    and upstream.port is not None
                )
                if upstream.scheme != "https" and not private_railway_http:
                    raise ValueError(
                        "upstream_market_data_base_url must use https in production, "
                        "except for an explicit-port Railway private-network origin"
                    )
            if self.upstream_market_data_base_url and not self.upstream_api_key:
                raise ValueError(
                    "upstream_api_key is required when the production market-data URL is configured"
                )
        if (
            self.upstream_allowed_history_start is not None
            and self.upstream_allowed_history_end is not None
            and self.upstream_allowed_history_start > self.upstream_allowed_history_end
        ):
            raise ValueError(
                "upstream_allowed_history_start must be <= upstream_allowed_history_end"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """Return CORS origins as a parsed list."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def cors_method_list(self) -> list[str]:
        return [method.strip() for method in self.cors_allow_methods.split(",") if method.strip()]

    @property
    def cors_header_list(self) -> list[str]:
        return [header.strip() for header in self.cors_allow_headers.split(",") if header.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def api_prefix(self) -> str:
        """Versioned API prefix, e.g. /api/v1."""
        return f"/api/{self.api_version}"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def upstream_configured(self) -> bool:
        """True when an upstream base URL has been supplied."""
        return bool(self.upstream_market_data_base_url)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Caching ensures environment variables are read once and the same
    configuration object is shared across the application.
    """
    return Settings()


def get_settings_uncached() -> Settings:
    """Return a fresh Settings instance (useful for testing)."""
    return Settings()
