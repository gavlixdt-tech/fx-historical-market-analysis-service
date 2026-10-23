"""Historical feature computation."""

from __future__ import annotations

import math
from collections.abc import Sequence


def simple_returns(closes: Sequence[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev == 0:
            out.append(None)
        else:
            out.append((closes[i] - prev) / prev)
    return out


def log_returns(closes: Sequence[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            out.append(None)
        else:
            out.append(math.log(cur / prev))
    return out


def rolling_mean(values: Sequence[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    for i in range(window - 1, len(values)):
        chunk = values[i - window + 1 : i + 1]
        nums = [v for v in chunk if v is not None]
        if len(nums) < window:
            out[i] = None
            continue
        out[i] = sum(nums) / len(nums)
    return out


def rolling_std(values: Sequence[float | None], window: int, ddof: int = 1) -> list[float | None]:
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
        var = sum((v - mean) ** 2 for v in nums) / (len(nums) - ddof)
        out[i] = math.sqrt(var) if var >= 0 else None
    return out


def cumulative_return(returns: Sequence[float | None], window: int) -> list[float | None]:
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


def direction_consistency(returns: Sequence[float | None], window: int) -> list[float | None]:
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


def candle_range_pct(high: float, low: float, close: float) -> float | None:
    if close == 0:
        return None
    return (high - low) / close


def candle_body_ratio(open_: float, high: float, low: float, close: float) -> float | None:
    rng = high - low
    if rng == 0:
        return None
    return abs(close - open_) / rng


def max_drawdown(closes: Sequence[float]) -> float:
    if not closes:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak != 0:
            dd = (peak - c) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd
