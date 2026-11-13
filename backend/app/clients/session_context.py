"""Typed adapter for DST-aware historical session context.

Session labels are deterministic calendar context, not evidence of order flow.
The adapter validates the complete response and binds each observation to the
same candle-close information timestamp before it enters historical replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from backend.app.schemas.replay import ReplaySessionContextInput

MAX_SESSION_CONTEXT_BATCH = 1000
MAX_SESSION_CONTEXT_RESPONSE_BYTES = 2_000_000
SESSION_CONTEXT_PATH = "/api/v1/session-context"


class SessionContextIntegrationError(RuntimeError):
    """Raised when the session-context dependency is unavailable or invalid."""


def _validate_origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SessionContextIntegrationError(
            "Feature-engineering URL must be an HTTP(S) origin without credentials or path."
        )
    return base_url.rstrip("/")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionContextIntegrationError("Session-context timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _parse_observation(value: object, expected_timestamp: datetime) -> ReplaySessionContextInput:
    if not isinstance(value, dict):
        raise SessionContextIntegrationError("Session-context observation must be an object.")
    expected = _aware_utc(expected_timestamp)
    try:
        returned_at = datetime.fromisoformat(str(value["timestamp_utc"]).replace("Z", "+00:00"))
        returned_at = _aware_utc(returned_at)
        if returned_at != expected:
            raise SessionContextIntegrationError(
                "Feature-engineering response timestamp does not match the requested candle."
            )
        if value.get("contract_version") != "fx-session-context/v1":
            raise SessionContextIntegrationError("Unsupported session-context contract version.")
        active_sessions = value["active_sessions"]
        active_open_windows = value["active_open_windows"]
        active_kill_zones = value["active_kill_zones"]
        overlap = value["session_overlap_count"]
        if (
            not isinstance(active_sessions, list)
            or not all(isinstance(item, str) for item in active_sessions)
            or not isinstance(active_open_windows, list)
            or not all(isinstance(item, str) for item in active_open_windows)
            or not isinstance(active_kill_zones, list)
            or not all(isinstance(item, str) for item in active_kill_zones)
            or not isinstance(overlap, int)
            or isinstance(overlap, bool)
            or overlap != len(active_sessions)
            or len(set(active_sessions)) != len(active_sessions)
            or len(set(active_open_windows)) != len(active_open_windows)
            or len(set(active_kill_zones)) != len(active_kill_zones)
        ):
            raise SessionContextIntegrationError("Feature-engineering session fields are invalid.")
        return ReplaySessionContextInput(
            contract_version="fx-session-context/v1",
            observed_at=expected,
            available_at=expected,
            active_sessions=active_sessions,
            active_open_windows=active_open_windows,
            active_kill_zones=active_kill_zones,
            session_overlap_count=overlap,
            source_reference=(
                "fx-feature-engineering-service:"
                f"{value.get('algorithm', 'iana-local-session-windows')}:"
                f"{value.get('algorithm_version', 'unknown')}"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SessionContextIntegrationError):
            raise
        raise SessionContextIntegrationError(
            "Feature-engineering response did not match the session-context v1 contract."
        ) from exc


async def fetch_historical_session_contexts(
    *,
    base_url: str | None,
    auth_token: str | None,
    timestamps: list[datetime],
    instrument: str,
    timeout_seconds: float = 5.0,
    request_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[ReplaySessionContextInput] | None:
    """Fetch one validated context per candle timestamp; None means unconfigured."""
    if not base_url:
        return None
    origin = _validate_origin(base_url)
    if not timestamps:
        return []
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if request_id:
        headers["X-Request-ID"] = request_id
        headers["X-Correlation-ID"] = request_id

    contexts: list[ReplaySessionContextInput] = []
    try:
        async with httpx.AsyncClient(
            base_url=origin,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            for offset in range(0, len(timestamps), MAX_SESSION_CONTEXT_BATCH):
                batch = timestamps[offset : offset + MAX_SESSION_CONTEXT_BATCH]
                response = await client.post(
                    SESSION_CONTEXT_PATH,
                    json={
                        "instrument": instrument,
                        "timestamps": [
                            _aware_utc(timestamp).isoformat().replace("+00:00", "Z")
                            for timestamp in batch
                        ],
                    },
                    headers=headers,
                )
                if response.status_code in {401, 403}:
                    raise SessionContextIntegrationError(
                        "Feature-engineering service rejected its configured credential."
                    )
                if response.status_code >= 400:
                    raise SessionContextIntegrationError(
                        f"Feature-engineering service returned HTTP {response.status_code}."
                    )
                if len(response.content) > MAX_SESSION_CONTEXT_RESPONSE_BYTES:
                    raise SessionContextIntegrationError(
                        "Feature-engineering session-context response exceeded the size limit."
                    )
                payload = response.json()
                if (
                    not isinstance(payload, dict)
                    or payload.get("contract_version") != "fx-session-context/v1"
                    or not isinstance(payload.get("observations"), list)
                    or len(payload["observations"]) != len(batch)
                ):
                    raise SessionContextIntegrationError(
                        "Feature-engineering response did not match the session-context batch contract."
                    )
                contexts.extend(
                    _parse_observation(item, timestamp)
                    for item, timestamp in zip(payload["observations"], batch, strict=True)
                )
    except SessionContextIntegrationError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise SessionContextIntegrationError(
            "Feature-engineering session-context request failed or returned invalid JSON."
        ) from exc

    return contexts
