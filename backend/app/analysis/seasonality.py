"""Descriptive calendar-seasonality research over contiguous historical returns.

The module is deliberately non-predictive: it reports grouped historical
statistics and block-bootstrap intervals without assigning trading signals or
statistical significance.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import fsum
from random import Random
from statistics import median, stdev
from typing import Any, Literal
from zoneinfo import ZoneInfo

from backend.app.analysis.observations import Observation

BucketType = Literal["weekday", "hour_of_day", "month_of_year"]

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MINIMUM_INTERVAL_MULTIPLE = 0.9

_TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
}


def _mean(values: list[float]) -> float | None:
    return fsum(values) / len(values) if values else None


def _sample_std(values: list[float]) -> float | None:
    return stdev(values) if len(values) >= 2 else None


def _circular_block_bootstrap_interval(
    values: list[float], *, samples: int, block_size: int, seed: int
) -> tuple[float | None, float | None]:
    """Return a deterministic 95% interval using circular moving-block resampling."""
    count = len(values)
    if count < 2 or samples < 1:
        return None, None

    rng = Random(seed)  # noqa: S311 - deterministic research resampling, not security.
    block = min(block_size, count)
    means: list[float] = []
    for _ in range(samples):
        sampled: list[float] = []
        while len(sampled) < count:
            start = rng.randrange(count)
            take = min(block, count - len(sampled))
            sampled.extend(values[(start + offset) % count] for offset in range(take))
        means.append(fsum(sampled) / count)

    means.sort()
    lower_index = max(0, min(samples - 1, int(0.025 * (samples - 1))))
    upper_index = max(0, min(samples - 1, int(0.975 * (samples - 1))))
    return means[lower_index], means[upper_index]


def _bucket_definitions(bucket_type: BucketType) -> list[tuple[int, str]]:
    if bucket_type == "weekday":
        return list(enumerate(_WEEKDAYS))
    if bucket_type == "hour_of_day":
        return [(hour, f"{hour:02d}:00-{hour:02d}:59") for hour in range(24)]
    return list(enumerate(_MONTHS, start=1))


def _bucket_key(bucket_type: BucketType, local_timestamp: datetime) -> int:
    if bucket_type == "weekday":
        return local_timestamp.weekday()
    if bucket_type == "hour_of_day":
        return local_timestamp.hour
    return local_timestamp.month


def analyze_calendar_seasonality(
    observations: list[Observation],
    *,
    timeframe: str,
    timezone_name: str,
    bucket_types: list[BucketType],
    minimum_bucket_samples: int,
    bootstrap_samples: int,
    block_size: int,
    seed: int,
    maximum_gap_multiple: float = 1.5,
) -> dict[str, Any]:
    """Group contiguous close-to-close returns by local calendar buckets.

    A return is assigned to the calendar bucket of the ending candle timestamp.
    Returns spanning gaps larger than the configured timeframe multiple are
    excluded rather than treating a multi-period move as a single-period return.
    """
    if timeframe not in _TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if not observations:
        raise ValueError("at least one observation is required")
    zone = ZoneInfo(timezone_name)
    expected_seconds = _TIMEFRAME_SECONDS[timeframe]
    maximum_gap_seconds = expected_seconds * maximum_gap_multiple

    grouped: dict[str, dict[int, list[tuple[float, float]]]] = {
        bucket_type: defaultdict(list) for bucket_type in bucket_types
    }
    all_returns: list[float] = []
    all_ranges: list[float] = []
    excluded_gap_count = 0
    excluded_short_interval_count = 0

    for previous, current in zip(observations, observations[1:], strict=False):
        if previous.timestamp.tzinfo is None or current.timestamp.tzinfo is None:
            raise ValueError("seasonality observations must have timezone-aware timestamps")
        elapsed = (current.timestamp - previous.timestamp).total_seconds()
        if elapsed <= 0:
            raise ValueError("seasonality observations must be strictly chronological")
        if elapsed < expected_seconds * MINIMUM_INTERVAL_MULTIPLE:
            excluded_short_interval_count += 1
            continue
        if elapsed > maximum_gap_seconds:
            excluded_gap_count += 1
            continue
        if previous.close <= 0 or current.close <= 0:
            raise ValueError("seasonality close prices must be positive")

        value = current.close / previous.close - 1.0
        range_pct = (current.high - current.low) / current.close
        local_timestamp = current.timestamp.astimezone(zone)
        all_returns.append(value)
        all_ranges.append(range_pct)
        for bucket_type in bucket_types:
            key = _bucket_key(bucket_type, local_timestamp)
            grouped[bucket_type][key].append((value, range_pct))

    global_mean = _mean(all_returns)
    global_summary: dict[str, float | int | None] = {
        "return_observation_count": len(all_returns),
        "excluded_gap_return_count": excluded_gap_count,
        "excluded_short_interval_return_count": excluded_short_interval_count,
        "mean_return": global_mean,
        "median_return": median(all_returns) if all_returns else None,
        "realized_volatility": _sample_std(all_returns),
        "positive_return_rate": (
            sum(value > 0 for value in all_returns) / len(all_returns) if all_returns else None
        ),
        "mean_candle_range_pct": _mean(all_ranges),
    }

    results: list[dict[str, object]] = []
    dimension_index = 0
    for bucket_type in bucket_types:
        for key, label in _bucket_definitions(bucket_type):
            pairs = grouped[bucket_type].get(key, [])
            returns = [pair[0] for pair in pairs]
            ranges = [pair[1] for pair in pairs]
            count = len(returns)
            interval_lower: float | None = None
            interval_upper: float | None = None
            if count >= minimum_bucket_samples:
                interval_lower, interval_upper = _circular_block_bootstrap_interval(
                    returns,
                    samples=bootstrap_samples,
                    block_size=block_size,
                    seed=seed + dimension_index,
                )
            mean_return = _mean(returns)
            results.append(
                {
                    "dimension": bucket_type,
                    "bucket_key": str(key),
                    "bucket_label": label,
                    "observation_count": count,
                    "sample_status": (
                        "descriptive_sample"
                        if count >= minimum_bucket_samples
                        else "insufficient_sample"
                    ),
                    "mean_return": mean_return,
                    "median_return": median(returns) if returns else None,
                    "positive_return_rate": (
                        sum(value > 0 for value in returns) / count if count else None
                    ),
                    "realized_volatility": _sample_std(returns),
                    "mean_candle_range_pct": _mean(ranges),
                    "mean_return_interval_95_lower": interval_lower,
                    "mean_return_interval_95_upper": interval_upper,
                    "difference_from_global_mean": (
                        mean_return - global_mean
                        if mean_return is not None and global_mean is not None
                        else None
                    ),
                }
            )
            dimension_index += 1

    insufficient = sum(item["sample_status"] == "insufficient_sample" for item in results)
    return {
        "timezone": timezone_name,
        "timeframe": timeframe,
        "bucket_types": bucket_types,
        "global_summary": global_summary,
        "buckets": results,
        "minimum_bucket_samples": minimum_bucket_samples,
        "bootstrap": {
            "method": "circular moving-block bootstrap within each calendar bucket",
            "samples": bootstrap_samples,
            "block_size": block_size,
            "interval": "descriptive 95% interval for the bucket mean",
        },
        "insufficient_bucket_count": insufficient,
        "forecast_eligible": False,
        "limitations": [
            "This is retrospective descriptive seasonality research, not a forecast or trading signal.",
            "Returns are close-to-close and are assigned to the local calendar bucket of the ending candle timestamp.",
            "Returns with intervals shorter than the configured minimum interval multiple of the declared timeframe or longer than the configured maximum gap are excluded.",
            "The moving-block bootstrap interval is descriptive and does not establish statistical significance or predictive value.",
            "Calendar buckets can be affected by daylight-saving changes, market holidays, missing candles and provider sampling conventions.",
            "Source identity and original historical publication times remain subject to the upstream provenance contract.",
        ],
    }
