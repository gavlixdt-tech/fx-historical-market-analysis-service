"""Contract tests for the upstream `fx-market-data-service` payload shapes.

These tests validate the *shape* of the upstream payloads using explicitly
labelled synthetic fixtures. They never assert real market values, and the
fixtures are not market data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.schemas.upstream import (
    UpstreamHistoricalResponse,
    UpstreamProviderListResponse,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_historical_payload_matches_the_upstream_contract() -> None:
    payload = _load("upstream_history_synthetic.json")
    parsed = UpstreamHistoricalResponse.model_validate(payload)

    assert parsed.data is not None
    assert parsed.data.canonical_instrument == "SYNTH/USD"
    assert parsed.data.timeframe.value == "D1"
    assert parsed.data.price_basis.value == "bid"
    assert len(parsed.data.candles) == 2
    assert parsed.data.coverage.complete is False
    assert parsed.data.coverage.missing_intervals == ["2024-01-03T00:00:00Z"]
    assert parsed.data.validation_summary.valid == 2
    assert parsed.data.pagination.has_more is False
    assert parsed.meta.api_version == "v1"


def test_provider_payload_matches_the_upstream_contract() -> None:
    payload = _load("upstream_providers_synthetic.json")
    parsed = UpstreamProviderListResponse.model_validate(payload)

    assert parsed.data is not None
    assert len(parsed.data.providers) == 1
    provider = parsed.data.providers[0]
    assert provider.provider_id == "synthetic-test-adapter"
    assert provider.configured is True
    assert provider.connection_status == "connected"


def test_provider_payload_never_exposes_credentials() -> None:
    """Service 1 promises credential-free provider summaries."""
    payload = _load("upstream_providers_synthetic.json")
    serialised = json.dumps(payload).lower()
    for forbidden in ("api_key", "apikey", "password", "secret", "client_secret"):
        assert forbidden not in serialised


def test_missing_required_upstream_field_is_rejected() -> None:
    payload = _load("upstream_history_synthetic.json")
    del payload["data"]["coverage"]

    with pytest.raises(ValueError):
        UpstreamHistoricalResponse.model_validate(payload)


def test_unknown_upstream_timeframe_is_rejected() -> None:
    payload = _load("upstream_history_synthetic.json")
    payload["data"]["timeframe"] = "X999"

    with pytest.raises(ValueError):
        UpstreamHistoricalResponse.model_validate(payload)


def test_error_payload_matches_the_upstream_error_envelope() -> None:
    payload = _load("upstream_error_synthetic.json")

    assert payload["error"]["code"] == "unsupported_instrument"
    assert payload["error"]["request_id"]
