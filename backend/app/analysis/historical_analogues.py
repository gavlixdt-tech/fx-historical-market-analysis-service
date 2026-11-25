"""Similarity search over prior OHLC windows with leakage-safe outcome comparison.

The score ranks historical shape similarity only. It is not a probability,
forecast, causal explanation, or authorization to trade.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC
from statistics import median, pstdev, stdev
from typing import Any

from backend.app.analysis.observations import Observation


FEATURE_SET_VERSION = "ohlc-candle-anatomy-volume-aware-v2"
_FEATURE_WEIGHTS = (1.2, 1.5, 1.0, 1.2, 0.8, 0.8, 0.8, 1.0, 1.2, 1.0)
_VOLUME_FEATURE_WEIGHTS = (1.0, 0.8, 0.8, 1.0)
_SUPPORTED_VOLUME_KINDS = frozenset({"exchange_traded", "broker_tick", "venue_reported"})


def _returns(closes: Sequence[float]) -> list[float]:
    values: list[float] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        if previous <= 0 or current <= 0:
            raise ValueError("analogue close prices must be positive")
        values.append(math.log(current / previous))
    return values


def _max_drawdown(closes: Sequence[float]) -> float:
    peak = closes[0]
    maximum = 0.0
    for close in closes:
        peak = max(peak, close)
        if peak > 0:
            maximum = max(maximum, (peak - close) / peak)
    return maximum


def _window_features(
    bars: Sequence[Observation],
    start: int,
    end: int,
    *,
    include_volume_features: bool = False,
) -> dict[str, float]:
    window = bars[start : end + 1]
    closes = [bar.close for bar in window]
    returns = _returns(closes)
    volatility = stdev(returns) if len(returns) > 1 else 0.0
    absolute_move = sum(abs(value) for value in returns)
    cumulative = sum(returns)
    ranges: list[float] = []
    bodies: list[float] = []
    upper_wicks: list[float] = []
    lower_wicks: list[float] = []
    positive = 0
    for bar in window:
        candle_range = max(bar.high - bar.low, 1e-12)
        ranges.append(candle_range / bar.close)
        bodies.append(abs(bar.close - bar.open) / candle_range)
        upper_wicks.append((bar.high - max(bar.open, bar.close)) / candle_range)
        lower_wicks.append((min(bar.open, bar.close) - bar.low) / candle_range)
    positive = sum(1 for value in returns if value > 0)
    recent_returns = returns[-min(5, len(returns)) :]
    recent_volatility = stdev(recent_returns) if len(recent_returns) > 1 else 0.0
    volatility_ratio = recent_volatility / volatility if volatility > 1e-12 else 0.0
    features = {
        "cumulative_log_return": cumulative,
        "realized_volatility": volatility,
        "efficiency_ratio": abs(cumulative) / absolute_move if absolute_move > 1e-12 else 0.0,
        "mean_range_pct": sum(ranges) / len(ranges),
        "mean_body_to_range": sum(bodies) / len(bodies),
        "mean_upper_wick_ratio": sum(upper_wicks) / len(upper_wicks),
        "mean_lower_wick_ratio": sum(lower_wicks) / len(lower_wicks),
        "positive_return_rate": positive / len(returns) if returns else 0.0,
        "recent_to_full_volatility_ratio": volatility_ratio,
        "maximum_drawdown": _max_drawdown(closes),
    }
    if include_volume_features:
        volumes = [float(bar.volume) for bar in window if bar.volume is not None]
        positive_volumes = [value for value in volumes if value > 0]
        volume_baseline = median(positive_volumes) if positive_volumes else 1.0
        relative_volumes = [value / volume_baseline for value in volumes]
        log_relative_volumes = [math.log1p(value) for value in relative_volumes]
        volume_mean = sum(volumes) / len(volumes)
        volume_cv = (
            pstdev(volumes) / volume_mean
            if len(volumes) > 1 and volume_mean > 1e-12
            else 0.0
        )
        paired_returns = returns[-len(relative_volumes[1:]):] if len(relative_volumes) > 1 else []
        paired_log_volume = log_relative_volumes[1:]
        if len(paired_returns) > 1 and len(paired_returns) == len(paired_log_volume):
            mean_return = sum(paired_returns) / len(paired_returns)
            mean_volume = sum(paired_log_volume) / len(paired_log_volume)
            covariance = sum(
                (value - mean_return) * (activity - mean_volume)
                for value, activity in zip(paired_returns, paired_log_volume, strict=True)
            )
            return_variance = sum((value - mean_return) ** 2 for value in paired_returns)
            volume_variance = sum((value - mean_volume) ** 2 for value in paired_log_volume)
            volume_return_correlation = (
                covariance / math.sqrt(return_variance * volume_variance)
                if return_variance > 1e-24 and volume_variance > 1e-24
                else 0.0
            )
        else:
            volume_return_correlation = 0.0
        positive_activity = [
            abs(change) / activity
            for change, activity in zip(returns, relative_volumes[1:], strict=True)
            if activity > 0
        ]
        features.update({
            "mean_log_relative_volume": sum(log_relative_volumes) / len(log_relative_volumes),
            "volume_coefficient_of_variation": volume_cv,
            "volume_signed_return_correlation": volume_return_correlation,
            "absolute_return_per_relative_volume": (
                sum(positive_activity) / len(positive_activity) if positive_activity else 0.0
            ),
        })
    return features


def _robust_scales(vectors: list[list[float]]) -> list[float]:
    scales: list[float] = []
    for column in zip(*vectors, strict=True):
        center = median(column)
        mad = median([abs(value - center) for value in column]) * 1.4826
        if mad <= 1e-12:
            spread = pstdev(column) if len(column) > 1 else 0.0
            mad = spread if spread > 1e-12 else max(abs(center), 1.0)
        scales.append(mad)
    return scales


def _distance(
    left: list[float],
    right: list[float],
    scales: list[float],
    weights: tuple[float, ...],
) -> float:
    weighted = [
        weight * ((a - b) / scale) ** 2
        for a, b, scale, weight in zip(left, right, scales, weights, strict=True)
    ]
    return math.sqrt(sum(weighted) / sum(weights))


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _outcome(bars: Sequence[Observation], end: int, horizon: int) -> dict[str, float]:
    entry = bars[end].close
    future = bars[end + 1 : end + horizon + 1]
    if len(future) != horizon or entry <= 0:
        raise ValueError("analogue outcome window is incomplete")
    return {
        "forward_return": bars[end + horizon].close / entry - 1.0,
        "upside_excursion": max(bar.high for bar in future) / entry - 1.0,
        "downside_excursion": min(bar.low for bar in future) / entry - 1.0,
    }


def _summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "sample_count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "median": _quantile(values, 0.5),
        "p10": _quantile(values, 0.1),
        "p90": _quantile(values, 0.9),
        "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
        "sample_stddev": stdev(values) if len(values) > 1 else (0.0 if values else None),
    }


def retrieve_historical_analogues(
    bars: Sequence[Observation],
    *,
    instrument: str,
    timeframe: str,
    context_lookback: int,
    outcome_horizons: list[int],
    top_k: int,
    minimum_analogue_count: int,
) -> dict[str, Any]:
    """Rank past windows and compare their fully matured future outcomes."""
    if not bars:
        raise ValueError("historical analogue search requires observations")
    volume_kinds = {bar.volume_kind for bar in bars}
    volume_values_complete = all(
        bar.volume is not None and math.isfinite(float(bar.volume)) and float(bar.volume) >= 0
        for bar in bars
    )
    volume_semantics = next(iter(volume_kinds)) if len(volume_kinds) == 1 else None
    include_volume_features = (
        volume_values_complete
        and volume_semantics in _SUPPORTED_VOLUME_KINDS
        and any(float(bar.volume or 0.0) > 0 for bar in bars)
    )
    volume_context = {
        "status": "AVAILABLE_SOURCE_SPECIFIC" if include_volume_features else "WITHHELD",
        "volume_semantics": volume_semantics,
        "observation_count": len(bars),
        "complete_volume_observation_count": sum(bar.volume is not None for bar in bars),
        "interpretation": (
            "Volume features are source/provider-specific participation proxies, not consolidated global FX volume, aggressor delta, or evidence of participant identity."
            if include_volume_features else
            "Volume-derived similarity features are withheld because the full history lacks complete, consistently typed, supported volume semantics."
        ),
    }
    if len(bars) < context_lookback:
        return {
            "status": "insufficient_data",
            "candidate_window_count": 0,
            "analogue_count": 0,
            "query_start_index": 0,
            "query_end_index": len(bars) - 1,
            "query_features": {},
            "feature_set_version": FEATURE_SET_VERSION,
            "volume_context": volume_context,
            "analogues": [],
            "outcome_comparison": [],
        }
    if any(bars[index].timestamp >= bars[index + 1].timestamp for index in range(len(bars) - 1)):
        raise ValueError("historical analogue observations must be strictly chronological")
    if context_lookback < 10 or context_lookback > 100:
        raise ValueError("context_lookback must be between 10 and 100")
    if not outcome_horizons or outcome_horizons != sorted(set(outcome_horizons)):
        raise ValueError("outcome horizons must be strictly ascending and unique")
    max_horizon = max(outcome_horizons)
    query_start = len(bars) - context_lookback
    query_end = len(bars) - 1
    # Every analogue's entire outcome horizon must mature strictly before the
    # current query window begins. This is the key leakage barrier.
    last_candidate_start = query_start - context_lookback - max_horizon
    if last_candidate_start < 0:
        return {
            "status": "insufficient_data",
            "candidate_window_count": 0,
            "analogue_count": 0,
            "query_start_index": query_start,
            "query_end_index": query_end,
            "query_features": _window_features(
                bars, query_start, query_end, include_volume_features=include_volume_features
            ),
            "feature_set_version": FEATURE_SET_VERSION,
            "volume_context": volume_context,
            "analogues": [],
            "outcome_comparison": [],
        }

    query_features = _window_features(
        bars, query_start, query_end, include_volume_features=include_volume_features
    )
    feature_names = list(query_features)
    feature_weights = _FEATURE_WEIGHTS + (
        _VOLUME_FEATURE_WEIGHTS if include_volume_features else ()
    )
    query_vector = [query_features[name] for name in feature_names]
    candidates: list[dict[str, Any]] = []
    feature_vectors: list[list[float]] = []
    baseline_outcomes: dict[int, list[float]] = {horizon: [] for horizon in outcome_horizons}

    for start in range(last_candidate_start + 1):
        end = start + context_lookback - 1
        features = _window_features(
            bars, start, end, include_volume_features=include_volume_features
        )
        vector = [features[name] for name in feature_names]
        candidates.append({"start": start, "end": end, "features": features})
        feature_vectors.append(vector)
        for horizon in outcome_horizons:
            baseline_outcomes[horizon].append(_outcome(bars, end, horizon)["forward_return"])

    scales = _robust_scales(feature_vectors + [query_vector])
    for candidate, vector in zip(candidates, feature_vectors, strict=True):
        distance = _distance(query_vector, vector, scales, feature_weights)
        candidate["distance"] = distance
        candidate["similarity_score"] = 1.0 / (1.0 + distance)

    candidates.sort(key=lambda item: (float(item["distance"]), int(item["start"])))
    selected: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for candidate in candidates:
        start = int(candidate["start"])
        end = int(candidate["end"])
        interval = (start, end + max_horizon)
        if any(interval[0] <= other_end and interval[1] >= other_start for other_start, other_end in occupied):
            continue
        occupied.append(interval)
        selected.append(candidate)
        if len(selected) >= top_k:
            break

    analogues: list[dict[str, Any]] = []
    selected_outcomes: dict[int, list[float]] = {horizon: [] for horizon in outcome_horizons}
    for rank, candidate in enumerate(selected, start=1):
        start = int(candidate["start"])
        end = int(candidate["end"])
        outcomes: dict[str, dict[str, float]] = {}
        for horizon in outcome_horizons:
            values = _outcome(bars, end, horizon)
            outcomes[str(horizon)] = values
            selected_outcomes[horizon].append(values["forward_return"])
        start_time = bars[start].timestamp.astimezone(UTC).isoformat()
        end_time = bars[end].timestamp.astimezone(UTC).isoformat()
        analogue_key = (
            f"{instrument}|{timeframe}|{FEATURE_SET_VERSION}|{volume_semantics}|"
            f"{start_time}|{end_time}"
        )
        analogues.append({
            "rank": rank,
            "analogue_id": hashlib.sha256(analogue_key.encode()).hexdigest(),
            "window_start": start_time,
            "window_end": end_time,
            "outcome_window_end": bars[end + max_horizon].timestamp.astimezone(UTC).isoformat(),
            "similarity_score": round(float(candidate["similarity_score"]), 8),
            "robust_distance": round(float(candidate["distance"]), 8),
            "features": candidate["features"],
            "outcomes_by_horizon_bars": outcomes,
        })

    comparison: list[dict[str, Any]] = []
    for horizon in outcome_horizons:
        analogue_values = selected_outcomes[horizon]
        baseline_values = baseline_outcomes[horizon]
        analogue_summary = _summary(analogue_values)
        baseline_summary = _summary(baseline_values)
        analogue_mean = analogue_summary["mean"]
        baseline_mean = baseline_summary["mean"]
        analogue_positive = analogue_summary["positive_rate"]
        baseline_positive = baseline_summary["positive_rate"]
        comparison.append({
            "horizon_bars": horizon,
            "analogue_outcomes": analogue_summary,
            "historical_baseline": baseline_summary,
            "mean_return_difference_vs_baseline": (
                analogue_mean - baseline_mean
                if analogue_mean is not None and baseline_mean is not None else None
            ),
            "positive_rate_difference_vs_baseline": (
                analogue_positive - baseline_positive
                if analogue_positive is not None and baseline_positive is not None else None
            ),
            "baseline_uses_overlapping_windows": True,
            "interpretation": "descriptive nearest-neighbour sample comparison; not a forecast or statistical significance test",
        })

    return {
        "status": "completed" if len(analogues) >= minimum_analogue_count else "insufficient_analogues",
        "candidate_window_count": len(candidates),
        "analogue_count": len(analogues),
        "query_start_index": query_start,
        "query_end_index": query_end,
        "query_features": query_features,
        "feature_set_version": FEATURE_SET_VERSION,
        "volume_context": volume_context,
        "analogues": analogues,
        "outcome_comparison": comparison,
    }
