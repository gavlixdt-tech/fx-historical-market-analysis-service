from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.clients.session_context import (
    SessionContextIntegrationError,
    fetch_historical_session_contexts,
)


def _timestamp(offset_minutes: int = 0) -> datetime:
    return datetime(2026, 10, 26, 8, 0, tzinfo=UTC) + timedelta(minutes=offset_minutes)


def _window(key: str, kind: str, active: bool) -> dict:
    return {"key": key, "kind": kind, "active": active}


def _observation(timestamp: datetime) -> dict:
    sessions = [
        _window(key, "session", key in {"london", "new_york"})
        for key in (
            "wellington",
            "sydney",
            "tokyo",
            "hong_kong",
            "singapore",
            "frankfurt",
            "london",
            "new_york",
        )
    ]
    open_windows = [
        _window(key, "open_window", key == "london_open")
        for key in ("sydney_open", "tokyo_open", "frankfurt_open", "london_open")
    ]
    kill_zones = [
        _window(key, "kill_zone", key == "ict_london")
        for key in (
            "ict_asia",
            "ict_london",
            "ict_new_york_am",
            "ict_london_close",
            "ict_new_york_pm",
        )
    ]
    return {
        "contract_version": "fx-session-context/v1",
        "algorithm": "iana-local-session-windows",
        "algorithm_version": "1.0.0",
        "instrument": "EUR/USD",
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "active_sessions": ["london", "new_york"],
        "active_open_windows": ["london_open"],
        "active_kill_zones": ["ict_london"],
        "session_overlap_count": 2,
        "is_session_overlap": True,
        "sessions": sessions,
        "open_windows": open_windows,
        "kill_zones": kill_zones,
    }



@pytest.mark.asyncio
async def test_fetches_and_validates_historical_session_context() -> None:
    timestamps = [_timestamp(), _timestamp(5)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["instrument"] == "EUR/USD"
        assert len(body["timestamps"]) == 2
        return httpx.Response(
            200,
            json={
                "contract_version": "fx-session-context/v1",
                "instrument": "EUR/USD",
                "observations": [_observation(value) for value in timestamps],
            },
        )

    contexts = await fetch_historical_session_contexts(
        base_url="https://feature-engineering.example",
        auth_token="test-bearer-token",
        timestamps=timestamps,
        instrument="EUR/USD",
        request_id="test-request-id",
        transport=httpx.MockTransport(handler),
    )

    assert len(contexts or []) == 2
    assert contexts is not None
    assert contexts[0].active_sessions == ["london", "new_york"]
    assert contexts[0].session_overlap_count == 2
    assert contexts[0].observed_at == timestamps[0]
    assert contexts[0].available_at == timestamps[0]
    assert contexts[0].source_reference.startswith("fx-feature-engineering-service:")
    assert requests[0].headers["Authorization"] == "Bearer test-bearer-token"
    assert requests[0].headers["X-Correlation-ID"] == requests[0].headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_rejects_context_returned_for_a_different_timestamp() -> None:
    timestamp = _timestamp()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "contract_version": "fx-session-context/v1",
                "instrument": "EUR/USD",
                "observations": [_observation(timestamp + timedelta(minutes=1))],
            },
        )

    with pytest.raises(SessionContextIntegrationError, match="timestamp"):
        await fetch_historical_session_contexts(
            base_url="https://feature-engineering.example",
            auth_token=None,
            timestamps=[timestamp],
            instrument="EUR/USD",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_rejects_inconsistent_session_overlap_count() -> None:
    timestamp = _timestamp()
    observation = _observation(timestamp)
    observation["session_overlap_count"] = 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "contract_version": "fx-session-context/v1",
                "instrument": "EUR/USD",
                "observations": [observation],
            },
        )

    with pytest.raises(SessionContextIntegrationError, match="session fields"):
        await fetch_historical_session_contexts(
            base_url="https://feature-engineering.example",
            auth_token=None,
            timestamps=[timestamp],
            instrument="EUR/USD",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_unconfigured_dependency_is_explicitly_absent() -> None:
    result = await fetch_historical_session_contexts(
        base_url=None,
        auth_token=None,
        timestamps=[_timestamp()],
        instrument="EUR/USD",
    )

    assert result is None
