from datetime import UTC, datetime

import pytest

from backend.app.analysis.observations import (
    Observation,
    ensure_sorted,
    from_mapping,
    validate_minimum,
)


def test_from_mapping_and_coerce() -> None:
    raw = {
        "timestamp": "2024-01-02T00:00:00Z",
        "open": "1.1",
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
    }
    obs = from_mapping(raw)
    assert obs.open == 1.1
    assert obs.timestamp.tzinfo is not None


def test_ensure_sorted_rejects_duplicates() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    obs = [Observation(timestamp=ts, open=1, high=1, low=1, close=1)] * 2
    with pytest.raises(ValueError):
        ensure_sorted(obs)


def test_validate_minimum() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    obs = [Observation(timestamp=ts, open=1, high=1, low=1, close=1)]
    with pytest.raises(ValueError):
        validate_minimum(obs, 2)
