"""Interpretable rule-based regime classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.app.analysis.observations import Observation


@dataclass(frozen=True)
class RegimeConfig:
    return_window: int = 20
    volatility_window: int = 20
    long_volatility_window: int = 60
    trend_threshold: float = 0.01
    high_volatility_threshold: float = 0.02
    low_volatility_threshold: float = 0.005
    direction_consistency_threshold: float = 0.6
    range_bound_consistency: float = 0.3
    min_observations: int = 50


@dataclass(frozen=True)
class RegimeObservation:
    index: int
    timestamp: str
    regime: str
    direction: str
    volatility: str
    cumulative_return: float | None
    volatility_value: float | None
    direction_consistency: float | None


_REGIME_LABELS = (
    "upward_drift",
    "downward_drift",
    "range_bound",
    "high_volatility",
    "low_volatility",
    "mixed_or_uncertain",
    "unclassified",
)


def classify_regimes(
    observations: Sequence[Observation], config: RegimeConfig
) -> list[RegimeObservation]:
    closes = [o.close for o in observations]
    returns = [None] + [  # align length
        (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] != 0 else None
        for i in range(1, len(closes))
    ]
    # Use simple_returns semantics (first is None).
    from backend.app.analysis.features import simple_returns as _sr

    returns = _sr(closes)
    cumret = _cumulative(returns, config.return_window)
    vol = _rolling_std(returns, config.volatility_window)
    consistency = _direction_consistency(returns, config.return_window)

    out: list[RegimeObservation] = []
    warmup = max(config.return_window, config.volatility_window, config.long_volatility_window)
    for i in range(len(observations)):
        if i + 1 < warmup:
            out.append(
                RegimeObservation(
                    index=i,
                    timestamp=observations[i].timestamp.isoformat(),
                    regime="unclassified",
                    direction="unknown",
                    volatility="unknown",
                    cumulative_return=None,
                    volatility_value=None,
                    direction_consistency=None,
                )
            )
            continue
        cr = cumret[i]
        v = vol[i]
        c = consistency[i]
        if cr is None or v is None or c is None:
            out.append(
                RegimeObservation(
                    index=i,
                    timestamp=observations[i].timestamp.isoformat(),
                    regime="unclassified",
                    direction="unknown",
                    volatility="unknown",
                    cumulative_return=cr,
                    volatility_value=v,
                    direction_consistency=c,
                )
            )
            continue
        # volatility dimension
        if v >= config.high_volatility_threshold:
            vol_label = "high"
        elif v <= config.low_volatility_threshold:
            vol_label = "low"
        else:
            vol_label = "normal"
        # direction dimension
        if cr >= config.trend_threshold and abs(c) >= config.direction_consistency_threshold:
            dir_label = "up"
        elif cr <= -config.trend_threshold and abs(c) >= config.direction_consistency_threshold:
            dir_label = "down"
        elif abs(c) <= config.range_bound_consistency:
            dir_label = "range"
        else:
            dir_label = "mixed"
        # primary label
        if vol_label == "high":
            primary = "high_volatility"
        elif vol_label == "low" and dir_label in ("mixed", "range"):
            primary = "low_volatility"
        elif dir_label == "up":
            primary = "upward_drift"
        elif dir_label == "down":
            primary = "downward_drift"
        elif dir_label == "range":
            primary = "range_bound"
        else:
            primary = "mixed_or_uncertain"
        out.append(
            RegimeObservation(
                index=i,
                timestamp=observations[i].timestamp.isoformat(),
                regime=primary,
                direction=dir_label,
                volatility=vol_label,
                cumulative_return=cr,
                volatility_value=v,
                direction_consistency=c,
            )
        )
    return out


def _rolling_std(values: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 1:
        return out
    for i in range(window - 1, len(values)):
        chunk = values[i - window + 1 : i + 1]
        nums = [v for v in chunk if v is not None]
        if len(nums) < window:
            out[i] = None
            continue
        mean = sum(nums) / len(nums)
        var = sum((v - mean) ** 2 for v in nums) / (len(nums) - 1)
        out[i] = (var**0.5) if var >= 0 else None
    return out


def _cumulative(returns: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(returns)
    if window <= 0:
        return out
    for i in range(window - 1, len(returns)):
        chunk = returns[i - window + 1 : i + 1]
        nums = [v for v in chunk if v is not None]
        if len(nums) < window:
            out[i] = None
            continue
        product = 1.0
        for r in nums:
            product *= 1.0 + r
        out[i] = product - 1.0
    return out


def _direction_consistency(returns: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(returns)
    if window <= 0:
        return out
    for i in range(window - 1, len(returns)):
        chunk = returns[i - window + 1 : i + 1]
        if any(v is None for v in chunk):
            out[i] = None
            continue
        signs = [1.0 if (v or 0) > 0 else (-1.0 if (v or 0) < 0 else 0.0) for v in chunk]
        out[i] = sum(signs) / len(signs)
    return out
