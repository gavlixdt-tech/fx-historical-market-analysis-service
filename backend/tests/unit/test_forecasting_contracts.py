from datetime import UTC

from backend.app.analysis.forecasting import (
    FORECAST_FEATURE_NAMES,
    ForecastingProblemSpec,
    generate_labels,
    resolve_eligibility_exclusions,
    validate_eligibility_rules,
)


def _observations(n: int = 20):
    from datetime import datetime, timedelta

    from backend.app.analysis.observations import Observation

    out = []
    for i in range(n):
        out.append(
            Observation(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i),
                open=1.0,
                high=1.01,
                low=0.99,
                close=1.0 + 0.001 * i,
                volume=1000.0,
            )
        )
    return out


def test_validate_eligibility_rules_accepts_supported_forms():
    assert validate_eligibility_rules(["0", "exclude_index:2", "exclude:3", "5"]) == []


def test_validate_eligibility_rules_rejects_invalid_forms():
    errors = validate_eligibility_rules(["foo", "exclude_index:-1", "exclude_index:x", ""])
    assert len(errors) == 4


def test_resolve_eligibility_exclusions_bounds_and_overlap():
    assert resolve_eligibility_exclusions(["0", "exclude_index:2", "2"], 5) == {0, 2}
    try:
        resolve_eligibility_exclusions(["10"], 5)
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_generate_labels_marks_excluded_without_horizon_shift():
    spec = ForecastingProblemSpec(
        problem_id="p",
        prediction_horizon=2,
        target_type="future_return",
        eligibility_rules=["1", "exclude_index:3"],
        neutral_threshold=None,
    )
    # neutral_threshold not required for future_return
    labels = generate_labels(_observations(8), spec)
    assert labels[1].status == "excluded"
    assert labels[3].status == "excluded"
    # A non-excluded reference still uses i + horizon.
    assert labels[0].future_index == 2
    assert labels[2].future_index == 4
    # Excluded index 3 does not make index 4 use a shifted future.
    assert labels[4].future_index == 6


def test_empty_eligibility_rules_preserve_labels():
    spec = ForecastingProblemSpec(problem_id="p", target_type="future_return")
    labels = generate_labels(_observations(8), spec)
    assert all(lab.status in {"valid", "missing_future_horizon"} for lab in labels)


def test_max_features_constant_length():
    assert len(FORECAST_FEATURE_NAMES) == 11
