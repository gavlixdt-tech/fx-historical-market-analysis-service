"""Bounded historical pattern research framework."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.app.analysis.observations import Observation


@dataclass(frozen=True)
class PatternSpec:
    pattern_id: str
    version: str = "1.0.0"
    lookback: int = 20
    outcome_horizon: int = 5
    min_events: int = 5
    params: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PatternEvent:
    index: int
    timestamp: str
    pattern_id: str
    outcome: float | None
    future_volatility: float | None


def _returns(observations: Sequence[Observation]) -> list[float]:
    closes = [o.close for o in observations]
    out: list[float] = [0.0]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out.append((closes[i] - prev) / prev if prev != 0 else 0.0)
    return out


def _rolling_std_series(values: list[float], window: int) -> list[float]:
    out = [0.0] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start : i + 1]
        if len(chunk) < 2:
            out[i] = 0.0
            continue
        mean = sum(chunk) / len(chunk)
        var = sum((x - mean) ** 2 for x in chunk) / (len(chunk) - 1)
        out[i] = var**0.5
    return out


def detect_events(observations: Sequence[Observation], spec: PatternSpec) -> list[int]:
    """Return indices (into observations) where the pattern condition holds."""
    n = len(observations)
    returns = _returns(observations)
    vol_short = _rolling_std_series(returns, min(spec.lookback, 10) or 5)
    vol_long = _rolling_std_series(returns, spec.lookback)
    events: list[int] = []
    pid = spec.pattern_id

    for i in range(spec.lookback, n):
        if pid == "volatility_compression_expansion":
            # Point-in-time: current short vol below long vol by ratio.
            ratio = spec.params.get("compression_ratio", 0.7)
            if vol_long[i] > 0 and vol_short[i] <= vol_long[i] * ratio:
                events.append(i)
        elif pid == "directional_persistence":
            chunk = returns[i - spec.lookback + 1 : i + 1]
            if all(r > 0 for r in chunk) or all(r < 0 for r in chunk):
                events.append(i)
        elif pid == "reversal_after_large_move":
            threshold = spec.params.get("move_threshold", 2.0)
            window_std = vol_long[i] if vol_long[i] > 0 else 1e-9
            if abs(returns[i]) >= threshold * window_std:
                # previous cumulative return opposite sign
                prev_cum = sum(returns[i - spec.lookback + 1 : i])
                if prev_cum == 0 or (prev_cum > 0) != (returns[i] > 0):
                    events.append(i)
        else:
            # Unknown pattern: no events.
            pass
    return events


def apply_overlap_policy(
    events: list[int], policy: str, outcome_horizon: int, min_gap: int = 1
) -> list[int]:
    if policy == "allow":
        return list(events)
    if policy == "min_gap":
        out: list[int] = []
        last = -(10**9)
        for e in events:
            if e - last >= min_gap:
                out.append(e)
                last = e
        return out
    if policy == "no_overlap_outcome":
        out = []
        last_end = -(10**9)
        for e in events:
            if e >= last_end:
                out.append(e)
                last_end = e + outcome_horizon + 1
        return out
    return list(events)


def compute_outcomes(
    observations: Sequence[Observation],
    events: list[int],
    horizon: int,
    pattern_id: str = "",
) -> list[PatternEvent]:
    closes = [o.close for o in observations]
    returns = _returns(observations)
    out: list[PatternEvent] = []
    for idx in events:
        outcome: float | None = None
        fut_vol: float | None = None
        if idx + horizon < len(closes) and closes[idx] != 0:
            outcome = closes[idx + horizon] / closes[idx] - 1.0
            window_returns = returns[idx + 1 : idx + horizon + 1]
            if len(window_returns) >= 2:
                mean = sum(window_returns) / len(window_returns)
                var = sum((r - mean) ** 2 for r in window_returns) / (len(window_returns) - 1)
                fut_vol = var**0.5
        out.append(
            PatternEvent(
                index=idx,
                timestamp=observations[idx].timestamp.isoformat(),
                pattern_id=pattern_id,
                outcome=outcome,
                future_volatility=fut_vol,
            )
        )
    return out


def baseline_outcomes(
    observations: Sequence[Observation], horizon: int, exclude: set[int]
) -> list[float]:
    closes = [o.close for o in observations]
    values: list[float] = []
    for i in range(len(closes)):
        if i in exclude:
            continue
        if i + horizon >= len(closes) or closes[i] == 0:
            continue
        values.append(closes[i + horizon] / closes[i] - 1.0)
    return values


def bootstrap_mean_ci(
    values: list[float],
    *,
    n_bootstrap: int = 200,
    block_size: int = 5,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)  # noqa: S311
    means: list[float] = []
    n = len(values)
    for _ in range(n_bootstrap):
        sampled: list[float] = []
        while len(sampled) < n:
            start = rng.randrange(n)
            block = values[start : start + block_size]
            sampled.extend(block)
        sampled = sampled[:n]
        means.append(sum(sampled) / len(sampled))
    means.sort()
    lo_idx = int((alpha / 2) * len(means))
    hi_idx = int((1 - alpha / 2) * len(means)) - 1
    lo_idx = max(0, min(lo_idx, len(means) - 1))
    hi_idx = max(0, min(hi_idx, len(means) - 1))
    return (means[lo_idx], means[hi_idx])


def permutation_p_value(
    pattern_values: list[float],
    baseline_values: list[float],
    *,
    n_permutations: int = 200,
    seed: int = 42,
) -> float:
    if not pattern_values or not baseline_values:
        return float("nan")
    rng = random.Random(seed)  # noqa: S311
    observed = (sum(pattern_values) / len(pattern_values)) - (
        sum(baseline_values) / len(baseline_values)
    )
    combined = list(pattern_values) + list(baseline_values)
    npat = len(pattern_values)
    count = 0
    for _ in range(n_permutations):
        rng.shuffle(combined)
        perm_pat = combined[:npat]
        perm_base = combined[npat:]
        diff = (sum(perm_pat) / len(perm_pat)) - (sum(perm_base) / len(perm_base))
        if abs(diff) >= abs(observed):
            count += 1
    return (count + 1) / (n_permutations + 1)


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[float]:
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        idx, p = indexed[rank - 1]
        val = p * m / rank
        if val > prev:
            val = prev
        prev = val
        q[idx] = min(val, 1.0)
    return q


def walk_forward_indices(n: int, train_ratio: float = 0.7) -> tuple[range, range]:
    split = int(n * train_ratio)
    if split < 1:
        split = 1
    if split >= n:
        split = n - 1
    return range(0, split), range(split, n)
