from datetime import UTC, datetime, timedelta

from backend.app.analysis.forecasting import (
    ForecastingProblemSpec,
    build_point_in_time_features,
)
from backend.app.analysis.observations import Observation


def test_point_in_time_features_preserve_resolved_instrument_identity() -> None:
    now = datetime.now(UTC) - timedelta(days=2)
    observations = [
        Observation(now, 1.0, 1.1, 0.9, 1.0),
        Observation(now + timedelta(days=1), 1.0, 1.2, 0.95, 1.1),
    ]
    spec = ForecastingProblemSpec(problem_id="instrument-identity-test")

    rows = build_point_in_time_features(
        observations,
        spec,
        lookback=2,
        instrument="EURUSD",
    )

    assert rows[0] is None
    assert rows[1] is not None
    assert rows[1]["instrument"] == "EURUSD"
    assert rows[1]["timeframe"] == "D1"


def test_point_in_time_feature_builder_keeps_legacy_optional_instrument_behavior() -> None:
    now = datetime.now(UTC) - timedelta(days=2)
    observations = [
        Observation(now, 1.0, 1.1, 0.9, 1.0),
        Observation(now + timedelta(days=1), 1.0, 1.2, 0.95, 1.1),
    ]
    rows = build_point_in_time_features(
        observations,
        ForecastingProblemSpec(problem_id="legacy-instrument-test"),
        lookback=2,
    )

    assert rows[1] is not None
    assert rows[1]["instrument"] is None
