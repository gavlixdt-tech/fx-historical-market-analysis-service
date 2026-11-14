from datetime import UTC, datetime, timedelta

from backend.app.analysis.observations import Observation, ensure_sorted
from backend.app.analysis.patterns import (
    PatternSpec,
    bootstrap_mean_ci,
    detect_events,
    partition_pattern_events,
    permutation_p_value,
)


def _obs(n: int = 60) -> list[Observation]:
    out = []
    price = 1.0
    dt = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(n):
        price *= 1.0 + (0.05 if i % 7 == 0 else -0.01)
        out.append(
            Observation(
                timestamp=dt + timedelta(days=i), open=price, high=price, low=price, close=price
            )
        )
    return ensure_sorted(out)


def test_detect_events_and_bootstrap() -> None:
    obs = _obs()
    spec = PatternSpec(pattern_id="directional_persistence", lookback=5, outcome_horizon=3)
    events = detect_events(obs, spec)
    assert isinstance(events, list)
    lo, hi = bootstrap_mean_ci([0.1, 0.2, -0.05, 0.03], n_bootstrap=50)
    assert lo <= hi
    p = permutation_p_value([0.1, 0.2], [0.0, -0.01], n_permutations=50)
    assert 0.0 <= p <= 1.0


def test_pattern_walk_forward_purges_training_outcomes_that_cross_test_boundary() -> None:
    train, test, purged, incomplete = partition_pattern_events(
        [2, 8, 9, 11, 12, 16, 17, 18],
        split_index=12,
        outcome_horizon=3,
        observation_count=20,
    )

    assert train == [2, 8]
    assert test == [12, 16]
    assert purged == 2
    assert incomplete == 2
    assert all(index + 3 < 12 for index in train)
    assert all(index + 3 < 20 for index in test)
