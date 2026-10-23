from datetime import UTC, datetime, timedelta

from backend.app.analysis.observations import Observation, ensure_sorted
from backend.app.analysis.regimes import RegimeConfig, classify_regimes


def _obs(n: int = 80) -> list[Observation]:
    out = []
    price = 1.0
    dt = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(n):
        price *= 1.001
        out.append(
            Observation(
                timestamp=dt + timedelta(days=i), open=price, high=price, low=price, close=price
            )
        )
    return ensure_sorted(out)


def test_classify_regimes() -> None:
    obs = _obs()
    cfg = RegimeConfig(
        return_window=10, volatility_window=10, long_volatility_window=20, min_observations=10
    )
    result = classify_regimes(obs, cfg)
    assert len(result) == len(obs)
    assert result[-1].regime in {
        "upward_drift",
        "downward_drift",
        "range_bound",
        "high_volatility",
        "low_volatility",
        "mixed_or_uncertain",
        "unclassified",
    }
