"""Read and verify versioned GFX Admin Console replay settings."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core.config import Settings
from backend.app.core.errors import UpstreamError

_SCOPE = "gfx:settings:read"
_TOKEN_CACHE: dict[str, Any] = {"token": None, "cache_key": None, "expires_at": 0.0}
_TOKEN_LOCK = threading.Lock()

_TIMEFRAME_SCOPE = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
    "MN1": "1mo",
}


class ReplayOperationalParameters(BaseModel):
    """Strict effective controls applied to a single replay request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    lookback: int = Field(ge=2, le=200)
    min_train_samples: int = Field(ge=10, le=1000)
    validation_mode: Literal["expanding", "rolling"]
    rolling_window: int = Field(ge=10, le=1500)
    embargo_periods: int = Field(ge=0, le=500)
    random_seed: int = Field(ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def validate_window(self) -> ReplayOperationalParameters:
        if self.validation_mode == "rolling" and self.rolling_window < self.min_train_samples:
            raise ValueError("rolling_window must be at least min_train_samples in rolling mode")
        return self


class ResolvedReplaySettings(BaseModel):
    """Verified parameters plus immutable settings provenance."""

    model_config = ConfigDict(frozen=True)

    parameters: ReplayOperationalParameters
    scope_id: str
    content_sha256: str
    active_version_id: str | None = None


def _canonical_digest(settings: dict[str, Any]) -> str:
    encoded = json.dumps(
        settings,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workload_token(
    client: httpx.Client,
    security_url: str,
    client_id: str,
    client_secret: str,
) -> str:
    now = time.monotonic()
    cache_key = hashlib.sha256(
        (security_url + "|" + client_id + "|" +
         hashlib.sha256(client_secret.encode("utf-8")).hexdigest()).encode("utf-8")
    ).hexdigest()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get("token")
        if (
            cached
            and hmac.compare_digest(str(_TOKEN_CACHE.get("cache_key", "")), cache_key)
            and now < float(_TOKEN_CACHE.get("expires_at", 0))
        ):
            return str(cached)
        try:
            response = client.post(
                f"{security_url}/api/v1/service-tokens/issue",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scopes": [_SCOPE],
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError(
                "Service 64 workload-token issuance failed.",
                details={"dependency": "fx-security-access-service"},
            ) from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        expires = payload.get("expires_in_seconds") if isinstance(payload, dict) else None
        if (
            not isinstance(token, str)
            or not token
            or isinstance(expires, bool)
            or not isinstance(expires, int)
            or not 1 <= expires <= 900
        ):
            raise UpstreamError(
                "Service 64 returned an invalid workload-token response.",
                details={"dependency": "fx-security-access-service"},
            )
        _TOKEN_CACHE.update({
            "token": token,
            "cache_key": cache_key,
            "expires_at": time.monotonic() + max(1, expires - 30),
        })
        return token


def resolve_historical_replay_settings(
    *, settings: Settings, instrument: str, timeframe: str
) -> ResolvedReplaySettings | None:
    """Resolve and digest-verify the effective global/scoped replay controls."""
    if not settings.gfx_settings_enabled:
        if settings.gfx_settings_required:
            raise UpstreamError(
                "Central replay settings are required but disabled.",
                details={"dependency": "fx-admin-console"},
            )
        return None

    canonical_instrument = instrument.strip().upper().replace("/", "")
    normalized_timeframe = _TIMEFRAME_SCOPE.get(timeframe)
    if len(canonical_instrument) != 6 or normalized_timeframe is None:
        raise UpstreamError(
            "Replay instrument or timeframe cannot be normalized for scoped settings.",
            details={"dependency": "fx-admin-console", "error_type": "settings_scope_invalid"},
        )
    scope_id = f"{canonical_instrument}|{normalized_timeframe}"
    assert settings.gfx_settings_service_url is not None
    assert settings.fx_security_service_url is not None
    assert settings.gfx_settings_client_id is not None
    assert settings.gfx_settings_client_secret is not None

    try:
        with httpx.Client(
            timeout=httpx.Timeout(3.0, connect=2.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            token = _workload_token(
                client,
                settings.fx_security_service_url,
                settings.gfx_settings_client_id,
                settings.gfx_settings_client_secret,
            )
            response = client.get(
                f"{settings.gfx_settings_service_url}/api/v1/settings/consumer/active",
                params={"scope": "instrument_timeframe", "scope_id": scope_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code in {401, 403}:
                with _TOKEN_LOCK:
                    _TOKEN_CACHE.update({
                        "token": None,
                        "cache_key": None,
                        "expires_at": 0.0,
                    })
            response.raise_for_status()
            payload = response.json()
    except UpstreamError:
        # Enabled central settings are authoritative; never silently bypass them.
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamError(
            "Enabled Admin Console replay settings are unavailable.",
            details={"dependency": "fx-admin-console"},
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
        raise UpstreamError(
            "Admin Console returned an invalid active replay settings response.",
            details={"dependency": "fx-admin-console"},
        )
    snapshot = payload["settings"]
    digest = payload.get("content_sha256")
    try:
        expected_digest = _canonical_digest(snapshot)
    except (TypeError, ValueError) as exc:
        raise UpstreamError(
            "Admin Console replay settings are not canonical JSON.",
            details={"dependency": "fx-admin-console"},
        ) from exc
    if not isinstance(digest, str) or not hmac.compare_digest(expected_digest, digest):
        raise UpstreamError(
            "Admin Console replay settings snapshot digest mismatch.",
            details={"dependency": "fx-admin-console", "error_type": "settings_digest_mismatch"},
        )

    keys = {
        "historical_replay.lookback": "lookback",
        "historical_replay.min_train_samples": "min_train_samples",
        "historical_replay.validation_mode": "validation_mode",
        "historical_replay.rolling_window": "rolling_window",
        "historical_replay.embargo_periods": "embargo_periods",
        "historical_replay.random_seed": "random_seed",
    }
    missing = set(keys) - set(snapshot)
    if missing:
        raise UpstreamError(
            "Active Admin Console settings snapshot is missing replay controls.",
            details={"dependency": "fx-admin-console", "missing_settings": sorted(missing)},
        )
    values = {target: snapshot[source] for source, target in keys.items()}
    try:
        parameters = ReplayOperationalParameters.model_validate(values)
    except ValueError as exc:
        raise UpstreamError(
            "Active Admin Console replay parameters failed validation.",
            details={"dependency": "fx-admin-console", "error_type": "settings_validation_failed"},
        ) from exc
    active_version_id = payload.get("active_version_id")
    return ResolvedReplaySettings(
        parameters=parameters,
        scope_id=scope_id,
        content_sha256=digest,
        active_version_id=active_version_id if isinstance(active_version_id, str) else None,
    )
