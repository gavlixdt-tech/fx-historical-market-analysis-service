from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.schemas.replay import ReplayObservationInput


def _base_observation(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    payload: dict[str, object] = {
        "timestamp": timestamp,
        "available_at": timestamp + timedelta(minutes=1),
        "open": 1.1,
        "high": 1.11,
        "low": 1.09,
        "close": 1.105,
        "source_record_id": "provider:EURUSD:M1:1",
    }
    payload.update(overrides)
    return payload


def test_session_context_is_accepted_with_explicit_availability() -> None:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    context = {
        "contract_version": "fx-session-context/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "active_sessions": ["london", "new_york"],
        "active_open_windows": ["london_open"],
        "active_kill_zones": ["ict_london"],
        "session_overlap_count": 2,
        "source_reference": "feature-engineering:context-123",
    }

    result = ReplayObservationInput.model_validate(
        _base_observation(session_context=context)
    )

    assert result.session_context is not None
    assert result.session_context.available_at > result.available_at
    assert result.session_context.session_overlap_count == 2


def test_session_context_rejects_inconsistent_overlap_count() -> None:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    context = {
        "contract_version": "fx-session-context/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "active_sessions": ["london", "new_york"],
        "active_open_windows": [],
        "active_kill_zones": [],
        "session_overlap_count": 1,
        "source_reference": "feature-engineering:context-123",
    }

    with pytest.raises(ValidationError, match="session_overlap_count"):
        ReplayObservationInput.model_validate(
            _base_observation(session_context=context)
        )


def test_lifecycle_context_requires_direction_after_sweep_confirmation() -> None:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    lifecycle = {
        "contract_version": "liquidity-sweep-lifecycle/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "state": "DISPLACEMENT_CONFIRMED",
        "source_event_id": "liquidity:event-123",
    }

    with pytest.raises(ValidationError, match="require a direction"):
        ReplayObservationInput.model_validate(
            _base_observation(liquidity_lifecycle=lifecycle)
        )


def test_context_observation_cannot_postdate_its_candle() -> None:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    context = {
        "contract_version": "fx-session-context/v1",
        "observed_at": timestamp + timedelta(seconds=1),
        "available_at": timestamp + timedelta(minutes=2),
        "active_sessions": [],
        "active_open_windows": [],
        "active_kill_zones": [],
        "session_overlap_count": 0,
        "source_reference": "feature-engineering:context-123",
    }

    with pytest.raises(ValidationError, match="later than the candle timestamp"):
        ReplayObservationInput.model_validate(
            _base_observation(session_context=context)
        )



def test_lifecycle_context_accepts_expected_direction() -> None:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    lifecycle = {
        "contract_version": "liquidity-sweep-lifecycle/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "state": "DISPLACEMENT_CONFIRMED",
        "expected_direction": "bearish",
        "source_event_id": "liquidity:event-124",
    }

    result = ReplayObservationInput.model_validate(
        _base_observation(liquidity_lifecycle=lifecycle)
    )

    assert result.liquidity_lifecycle is not None
    assert result.liquidity_lifecycle.expected_direction == "bearish"



def test_context_features_are_attached_only_after_their_availability_cutoff() -> None:
    from backend.app.analysis.replay import _attach_market_context_features

    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    candle_available_at = timestamp + timedelta(minutes=1)
    session_context = {
        "contract_version": "fx-session-context/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(seconds=30),
        "active_sessions": ["london", "new_york"],
        "active_open_windows": ["london_open"],
        "active_kill_zones": ["ict_london"],
        "session_overlap_count": 2,
        "source_reference": "feature-engineering:context-125",
    }
    lifecycle_context = {
        "contract_version": "liquidity-sweep-lifecycle/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(seconds=45),
        "state": "MIDPOINT_CONSOLIDATION_CANDIDATE",
        "expected_direction": "bullish",
        "source_event_id": "liquidity:event-125",
    }
    observation = ReplayObservationInput.model_validate(
        _base_observation(
            available_at=candle_available_at,
            session_context=session_context,
            liquidity_lifecycle=lifecycle_context,
        )
    )
    features = [{"reference_index": 0}]
    names, has_context = _attach_market_context_features(
        features, [observation], [candle_available_at]
    )

    assert has_context is True
    assert "session_london" in names
    assert features[0]["session_london"] == 1.0
    assert features[0]["session_new_york"] == 1.0
    assert features[0]["kill_zone_ict_london"] == 1.0
    assert features[0]["session_overlap_count"] == 2.0
    assert features[0]["liquidity_sweep_bullish"] == 1.0
    assert features[0]["liquidity_displacement_confirmed"] == 1.0
    assert features[0]["liquidity_midpoint_reached"] == 1.0
    assert features[0]["liquidity_midpoint_consolidation"] == 1.0


def test_late_context_is_null_and_cannot_enter_the_feature_row() -> None:
    from backend.app.analysis.replay import _attach_market_context_features

    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=2)
    candle_available_at = timestamp + timedelta(minutes=1)
    late_session_context = {
        "contract_version": "fx-session-context/v1",
        "observed_at": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "active_sessions": ["london"],
        "active_open_windows": [],
        "active_kill_zones": [],
        "session_overlap_count": 1,
        "source_reference": "feature-engineering:late-context",
    }
    observation = ReplayObservationInput.model_validate(
        _base_observation(
            available_at=candle_available_at,
            session_context=late_session_context,
        )
    )
    features = [{"reference_index": 0}]
    _attach_market_context_features(features, [observation], [candle_available_at])

    assert features[0]["session_london"] is None
    assert features[0]["session_overlap_count"] is None
    assert features[0]["liquidity_sweep_bullish"] is None
