from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest

from backend.app.clients import operational_settings as client_module
from backend.app.clients.operational_settings import resolve_historical_replay_settings
from backend.app.core.config import Settings
from backend.app.core.errors import UpstreamError


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "testing",
        "gfx_settings_enabled": True,
        "gfx_settings_required": True,
        "gfx_settings_service_url": "https://admin.example",
        "fx_security_service_url": "https://security.example",
        "gfx_settings_client_id": "service2-client-identity",
        "gfx_settings_client_secret": "s" * 48,
    }
    values.update(overrides)
    return Settings(**values)


def _snapshot() -> dict[str, Any]:
    return {
        "historical_replay.lookback": 20,
        "historical_replay.min_train_samples": 30,
        "historical_replay.validation_mode": "expanding",
        "historical_replay.rolling_window": 250,
        "historical_replay.embargo_periods": 1,
        "historical_replay.random_seed": 42,
    }


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "upstream error",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        *,
        settings_status: int = 200,
        pending_items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.settings_status = settings_status
        self.pending_items = pending_items or []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any]) -> _Response:
        self.posts.append((url, json))
        if url.endswith("/service-tokens/issue"):
            return _Response({"access_token": "workload-token", "expires_in_seconds": 300})
        return _Response({"status": json.get("status"), "idempotent_replay": False})

    def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str],
    ) -> _Response:
        self.gets.append((url, {"params": params, "headers": headers}))
        if url.endswith("/settings/consumer/pending"):
            return _Response({"items": self.pending_items})
        snapshot = _snapshot()
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        return _Response(
            {
                "active_version_id": "version-123",
                "content_sha256": digest,
                "settings": snapshot,
            },
            self.settings_status,
        )


def test_resolves_digest_verified_instrument_timeframe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    resolved = resolve_historical_replay_settings(
        settings=_settings(),
        instrument="EUR/USD",
        timeframe="H1",
    )

    assert resolved is not None
    assert resolved.scope_id == "EURUSD|1h"
    assert resolved.active_version_id == "version-123"
    assert resolved.parameters.lookback == 20
    assert resolved.parameters.embargo_periods == 1
    assert fake.posts[0][0] == "https://security.example/api/v1/service-tokens/issue"
    assert fake.posts[0][1]["scopes"] == ["gfx:settings:read", "gfx:settings:ack"]
    assert fake.gets[0][0] == "https://admin.example/api/v1/settings/consumer/pending"
    assert fake.gets[1][0] == "https://admin.example/api/v1/settings/consumer/active"
    assert fake.gets[1][1]["params"] == {
        "scope": "instrument_timeframe",
        "scope_id": "EURUSD|1h",
    }
    assert fake.gets[0][1]["headers"]["Authorization"] == "Bearer workload-token"


def test_enabled_settings_fail_closed_when_admin_console_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(settings_status=503)
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    with pytest.raises(UpstreamError, match="Enabled Admin Console replay settings are unavailable"):
        resolve_historical_replay_settings(
            settings=_settings(),
            instrument="EUR/USD",
            timeframe="H1",
        )


def test_enabled_settings_reject_a_tampered_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    class TamperedClient(_FakeClient):
        def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str],
        ) -> _Response:
            response = super().get(url, params=params, headers=headers)
            if url.endswith("/settings/consumer/pending"):
                return response
            payload = response.json()
            payload["settings"]["historical_replay.lookback"] = 99
            return _Response(payload)

    fake = TamperedClient()
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    with pytest.raises(UpstreamError, match="snapshot digest mismatch"):
        resolve_historical_replay_settings(
            settings=_settings(),
            instrument="EUR/USD",
            timeframe="H1",
        )


def test_pending_candidate_with_invalid_rolling_window_is_rejected_but_active_settings_remain_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_snapshot = _snapshot()
    candidate_snapshot["historical_replay.validation_mode"] = "rolling"
    candidate_snapshot["historical_replay.rolling_window"] = 20
    digest = hashlib.sha256(
        json.dumps(
            candidate_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    candidate = {
        "id": "invalid-rolling-version",
        "content_sha256": digest,
        "settings": candidate_snapshot,
    }
    fake = _FakeClient(pending_items=[candidate])
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    resolved = resolve_historical_replay_settings(
        settings=_settings(),
        instrument="EUR/USD",
        timeframe="H1",
    )

    assert resolved is not None
    assert resolved.parameters.validation_mode == "expanding"
    assert resolved.rejected_candidate_version_ids == ["invalid-rolling-version"]
    assert fake.posts[1][1]["status"] == "REJECTED"


def test_settings_disabled_does_not_call_remote_services(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_client(**_kwargs: Any) -> None:
        raise AssertionError("remote services must not be called when settings are disabled")

    monkeypatch.setattr(client_module.httpx, "Client", unexpected_client)
    assert resolve_historical_replay_settings(
        settings=Settings(environment="testing"),
        instrument="EUR/USD",
        timeframe="H1",
    ) is None


def test_settings_enabled_requires_required_flag() -> None:
    with pytest.raises(ValueError, match="requires GFX_SETTINGS_REQUIRED=true"):
        _settings(gfx_settings_required=False)



def test_pending_candidate_is_digest_checked_and_acknowledged_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    candidate = {
        "id": "candidate-version-123",
        "content_sha256": digest,
        "settings": snapshot,
        "scope": "global",
    }
    fake = _FakeClient(pending_items=[candidate])
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    resolved = resolve_historical_replay_settings(
        settings=_settings(),
        instrument="EUR/USD",
        timeframe="H1",
    )

    assert resolved is not None
    ack_url, ack_payload = fake.posts[1]
    assert ack_url == "https://admin.example/api/v1/settings/consumer/acknowledgements"
    assert ack_payload == {
        "version_id": "candidate-version-123",
        "content_sha256": digest,
        "status": "READY",
        "detail": "Service 2 validated the candidate digest and all historical replay controls.",
    }


def test_pending_candidate_with_bad_digest_blocks_settings_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(pending_items=[{
        "id": "candidate-version-123",
        "content_sha256": "0" * 64,
        "settings": _snapshot(),
    }])
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    with pytest.raises(UpstreamError, match="candidate digest mismatch"):
        resolve_historical_replay_settings(
            settings=_settings(),
            instrument="EUR/USD",
            timeframe="H1",
        )



def test_rejected_workload_token_is_invalidated_without_clearing_a_replacement() -> None:
    client_module._TOKEN_CACHE.update({
        "token": "replacement-token",
        "cache_key": "replacement-key",
        "expires_at": 9999999999.0,
    })

    client_module._invalidate_workload_token("revoked-old-token")

    assert client_module._TOKEN_CACHE == {
        "token": "replacement-token",
        "cache_key": "replacement-key",
        "expires_at": 9999999999.0,
    }

    client_module._invalidate_workload_token("replacement-token")

    assert client_module._TOKEN_CACHE == {
        "token": None,
        "cache_key": None,
        "expires_at": 0.0,
    }



def test_invalid_pending_candidate_is_rejected_and_active_settings_remain_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_snapshot = _snapshot()
    invalid_snapshot["historical_replay.validation_mode"] = "rolling"
    invalid_snapshot["historical_replay.rolling_window"] = 20
    digest = hashlib.sha256(
        json.dumps(
            invalid_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    candidate = {
        "id": "invalid-candidate-version-123",
        "content_sha256": digest,
        "settings": invalid_snapshot,
        "scope": "global",
    }
    fake = _FakeClient(pending_items=[candidate])
    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: fake)
    client_module._TOKEN_CACHE.update({"token": None, "cache_key": None, "expires_at": 0.0})

    resolved = resolve_historical_replay_settings(
        settings=_settings(),
        instrument="EUR/USD",
        timeframe="H1",
    )

    assert resolved is not None
    assert resolved.active_version_id == "version-123"
    assert resolved.parameters.validation_mode == "expanding"
    assert resolved.rejected_candidate_version_ids == ["invalid-candidate-version-123"]
    acknowledgement = next(
        payload for url, payload in fake.posts
        if url.endswith("/settings/consumer/acknowledgements")
    )
    assert acknowledgement["status"] == "REJECTED"
    assert acknowledgement["version_id"] == "invalid-candidate-version-123"
