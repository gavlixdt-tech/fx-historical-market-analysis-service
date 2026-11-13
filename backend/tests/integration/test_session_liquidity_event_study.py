from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.api.v1.routes.session_liquidity import (
    LiquidityEventObservation,
    SessionLiquidityEventStudyRequest,
    build_session_liquidity_event_study,
)

UTC = timezone.utc


def dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 12, hour, minute, tzinfo=UTC)


def event(
    event_id: str,
    instance_id: str,
    sweep_minute: int,
    *,
    available_minute: int = 55,
    observation_end_minute: int = 60,
    displacement_minute: int | None = None,
) -> LiquidityEventObservation:
    return LiquidityEventObservation(
        instrument="XAU/USD",
        timeframe="M1",
        session_key="london",
        session_instance_id=instance_id,
        source_event_id=event_id,
        direction="bullish",
        session_open_at=dt(8, 0),
        sweep_confirmed_at=dt(8, sweep_minute),
        available_at=dt(8, available_minute),
        observation_end_at=dt(8, observation_end_minute),
        displacement_confirmed_at=(
            dt(8, displacement_minute) if displacement_minute is not None else None
        ),
    )


def test_study_uses_first_sweep_per_session_and_right_censoring() -> None:
    payload = SessionLiquidityEventStudyRequest(
        analysis_cutoff=dt(9, 0),
        minimum_group_sample=5,
        events=[
            event("s1-first", "london-2026-11-12", 10, displacement_minute=20),
            event("s1-later", "london-2026-11-12", 15, available_minute=16),
            event(
                "s2-first",
                "london-2026-11-13",
                20,
                available_minute=30,
                observation_end_minute=60,
            ),
            event(
                "future-available",
                "london-2026-11-14",
                25,
                available_minute=55,
                observation_end_minute=60,
            ).model_copy(update={
                "available_at": dt(9, 5),
                "observation_end_at": dt(9, 10),
            }),
        ],
    )

    result = build_session_liquidity_event_study(payload)

    assert result["eligible_event_count"] == 3
    assert result["first_sweep_session_instance_count"] == 2
    group = result["groups"][0]
    assert group["first_sweep_session_instances"] == 2
    assert group["minutes_from_session_open_to_first_confirmed_sweep"]["median"] == 10
    assert group["post_sweep_time_to_displacement"]["events"] == 1
    assert group["post_sweep_time_to_displacement"]["censored"] == 1
    assert group["sample_status"] == "insufficient_sample"
    assert result["forecast_eligible"] is False


def test_cutoff_excludes_late_available_records() -> None:
    late = event(
        "late",
        "london-late",
        12,
        available_minute=55,
        observation_end_minute=60,
    )
    payload = SessionLiquidityEventStudyRequest(
        analysis_cutoff=dt(8, 30),
        events=[late],
    )

    result = build_session_liquidity_event_study(payload)

    assert result["eligible_event_count"] == 0
    assert result["excluded_after_cutoff_count"] == 1
    assert result["groups"] == []


def test_lifecycle_transition_cannot_precede_sweep_or_availability() -> None:
    with pytest.raises(ValidationError):
        event(
            "invalid",
            "london-invalid",
            10,
            available_minute=15,
            displacement_minute=20,
        )


def test_duplicate_source_event_ids_are_rejected() -> None:
    first = event("duplicate", "session-a", 10)
    second = event("duplicate", "session-b", 20)
    with pytest.raises(ValidationError):
        SessionLiquidityEventStudyRequest(
            analysis_cutoff=dt(9, 0),
            events=[first, second],
        )
