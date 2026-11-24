"""Causal, point-in-time market-structure extraction from OHLC observations.

This module describes observable price structure. It deliberately does not
claim that any structure guarantees a future move or is itself a trade signal.
All event detection uses data available at or before the event candle.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from statistics import median
from typing import Sequence

from backend.app.analysis.observations import Observation


@dataclass(frozen=True)
class StructureConfig:
    pivot_left: int = 3
    pivot_right: int = 3
    atr_window: int = 14
    equal_level_atr_tolerance: float = 0.12
    displacement_atr_multiple: float = 1.5
    minimum_range_bars: int = 12
    maximum_events: int = 500


@dataclass(frozen=True)
class StructureEvent:
    index: int
    timestamp: str
    kind: str
    direction: str
    level: float | None
    price: float
    strength: float
    evidence: dict[str, float | int | str | bool]


def _true_ranges(bars: Sequence[Observation]) -> list[float]:
    values: list[float] = []
    for i, bar in enumerate(bars):
        previous = bars[i - 1].close if i else bar.close
        values.append(max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous)))
    return values


def _rolling_mean(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def _pivot_high(bars: Sequence[Observation], index: int, left: int, right: int) -> bool:
    value = bars[index].high
    window = [b.high for b in bars[index-left:index+right+1]]
    return value == max(window) and window.count(value) == 1


def _pivot_low(bars: Sequence[Observation], index: int, left: int, right: int) -> bool:
    value = bars[index].low
    window = [b.low for b in bars[index-left:index+right+1]]
    return value == min(window) and window.count(value) == 1


def analyze_market_structure(
    bars: Sequence[Observation], config: StructureConfig | None = None
) -> dict[str, object]:
    """Extract swings, BOS/CHoCH, sweeps, gaps, blocks, candle anatomy and regimes."""
    cfg = config or StructureConfig()
    if cfg.pivot_left < 1 or cfg.pivot_right < 1 or cfg.atr_window < 2:
        raise ValueError("pivot windows and ATR window must be positive")
    if not 0 < cfg.equal_level_atr_tolerance <= 1:
        raise ValueError("equal_level_atr_tolerance must be in (0, 1]")
    if not isfinite(cfg.displacement_atr_multiple) or cfg.displacement_atr_multiple <= 0:
        raise ValueError("displacement_atr_multiple must be finite and positive")
    if cfg.minimum_range_bars < 2:
        raise ValueError("minimum_range_bars must be at least 2")
    if cfg.maximum_events < 1:
        raise ValueError("maximum_events must be positive")
    if len(bars) < max(cfg.pivot_left + cfg.pivot_right + 2, cfg.atr_window + 1):
        raise ValueError("insufficient observations for market-structure analysis")
    for i, bar in enumerate(bars):
        vals = (bar.open, bar.high, bar.low, bar.close)
        if not all(isfinite(v) for v in vals) or bar.low <= 0:
            raise ValueError(f"invalid OHLC values at index {i}")
        if i and bars[i].timestamp <= bars[i-1].timestamp:
            raise ValueError("observations must be strictly chronological")

    tr = _true_ranges(bars)
    atr = _rolling_mean(tr, cfg.atr_window)
    events: list[StructureEvent] = []
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    structure_direction = "unknown"
    last_broken_high: int | None = None
    last_broken_low: int | None = None

    def emit(i: int, kind: str, direction: str, level: float | None,
             strength: float, evidence: dict[str, float | int | str | bool]) -> None:
        if len(events) < cfg.maximum_events:
            events.append(StructureEvent(
                index=i, timestamp=bars[i].timestamp.isoformat(), kind=kind,
                direction=direction, level=level, price=bars[i].close,
                strength=round(max(0.0, min(1.0, strength)), 4), evidence=evidence,
            ))

    # Confirmed pivots are timestamped at the pivot candle but only become
    # available after pivot_right bars. No future candle leaks into decisions.
    for i in range(cfg.pivot_left, len(bars) - cfg.pivot_right):
        confirmed_at = i + cfg.pivot_right
        if _pivot_high(bars, i, cfg.pivot_left, cfg.pivot_right):
            swing_highs.append((i, bars[i].high))
            emit(confirmed_at, "swing_high", "bearish", bars[i].high, 0.55,
                 {"pivot_index": i, "confirmation_delay_bars": cfg.pivot_right})
        if _pivot_low(bars, i, cfg.pivot_left, cfg.pivot_right):
            swing_lows.append((i, bars[i].low))
            emit(confirmed_at, "swing_low", "bullish", bars[i].low, 0.55,
                 {"pivot_index": i, "confirmation_delay_bars": cfg.pivot_right})

    # Structural breaks are evaluated chronologically using only pivots already
    # confirmed at the current candle.
    highs_by_confirmation = {idx + cfg.pivot_right: (idx, value) for idx, value in swing_highs}
    lows_by_confirmation = {idx + cfg.pivot_right: (idx, value) for idx, value in swing_lows}
    active_high: tuple[int, float] | None = None
    active_low: tuple[int, float] | None = None
    for i, bar in enumerate(bars):
        if i in highs_by_confirmation:
            active_high = highs_by_confirmation[i]
        if i in lows_by_confirmation:
            active_low = lows_by_confirmation[i]
        current_atr = atr[i]
        if current_atr is None or current_atr <= 0:
            continue
        if active_high and bar.close > active_high[1] and last_broken_high != active_high[0]:
            kind = "break_of_structure" if structure_direction in ("bullish", "unknown") else "change_of_character"
            emit(i, kind, "bullish", active_high[1],
                 min(1.0, (bar.close-active_high[1])/current_atr),
                 {"broken_swing_index": active_high[0], "close_clearance_atr": (bar.close-active_high[1])/current_atr})
            structure_direction = "bullish"
            last_broken_high = active_high[0]
        if active_low and bar.close < active_low[1] and last_broken_low != active_low[0]:
            kind = "break_of_structure" if structure_direction in ("bearish", "unknown") else "change_of_character"
            emit(i, kind, "bearish", active_low[1],
                 min(1.0, (active_low[1]-bar.close)/current_atr),
                 {"broken_swing_index": active_low[0], "close_clearance_atr": (active_low[1]-bar.close)/current_atr})
            structure_direction = "bearish"
            last_broken_low = active_low[0]

        # Liquidity sweep: wick through a confirmed swing level, close back inside.
        if active_high and bar.high > active_high[1] and bar.close < active_high[1]:
            emit(i, "buy_side_liquidity_sweep", "bearish", active_high[1],
                 min(1.0, (bar.high-active_high[1])/current_atr),
                 {"wick_penetration_atr": (bar.high-active_high[1])/current_atr})
        if active_low and bar.low < active_low[1] and bar.close > active_low[1]:
            emit(i, "sell_side_liquidity_sweep", "bullish", active_low[1],
                 min(1.0, (active_low[1]-bar.low)/current_atr),
                 {"wick_penetration_atr": (active_low[1]-bar.low)/current_atr})

        body = abs(bar.close - bar.open)
        candle_range = max(bar.high - bar.low, 1e-12)
        upper_wick = bar.high - max(bar.open, bar.close)
        lower_wick = min(bar.open, bar.close) - bar.low
        if body / current_atr >= cfg.displacement_atr_multiple:
            emit(i, "bullish_displacement" if bar.close > bar.open else "bearish_displacement",
                 "bullish" if bar.close > bar.open else "bearish", None,
                 min(1.0, body/current_atr/3),
                 {"body_atr": body/current_atr, "body_to_range": body/candle_range})
        if body / candle_range <= 0.1 and (upper_wick + lower_wick) / candle_range >= 0.8:
            emit(i, "indecision_candle", "neutral", None, 0.4,
                 {"body_to_range": body/candle_range, "upper_wick_to_range": upper_wick/candle_range,
                  "lower_wick_to_range": lower_wick/candle_range})
        if lower_wick >= body * 2 and lower_wick > upper_wick:
            emit(i, "long_lower_rejection", "bullish", bar.low, min(1.0, lower_wick/candle_range),
                 {"wick_to_body": lower_wick/max(body, 1e-12)})
        if upper_wick >= body * 2 and upper_wick > lower_wick:
            emit(i, "long_upper_rejection", "bearish", bar.high, min(1.0, upper_wick/candle_range),
                 {"wick_to_body": upper_wick/max(body, 1e-12)})

        # Three-candle fair-value gaps; the event is known only on candle i.
        if i >= 2:
            if bars[i].low > bars[i-2].high:
                emit(i, "bullish_fair_value_gap", "bullish", bars[i-2].high, 0.6,
                     {"gap_size": bars[i].low-bars[i-2].high, "gap_atr": (bars[i].low-bars[i-2].high)/current_atr})
            if bars[i].high < bars[i-2].low:
                emit(i, "bearish_fair_value_gap", "bearish", bars[i-2].low, 0.6,
                     {"gap_size": bars[i-2].low-bars[i].high, "gap_atr": (bars[i-2].low-bars[i].high)/current_atr})

        # Equal highs/lows use a volatility-scaled tolerance, not a fixed pip
        # threshold, so the rule can be applied across instruments.
        tolerance = current_atr * cfg.equal_level_atr_tolerance
        # Only swings whose right-side confirmation bars have closed are
        # eligible. The current candle is compared with those known levels;
        # future pivots never enter this event's evidence.
        prior_highs = [
            level for pivot_index, level in swing_highs
            if pivot_index + cfg.pivot_right <= i
        ]
        prior_lows = [
            level for pivot_index, level in swing_lows
            if pivot_index + cfg.pivot_right <= i
        ]
        matching_highs = [level for level in prior_highs if abs(bar.high - level) <= tolerance]
        matching_lows = [level for level in prior_lows if abs(bar.low - level) <= tolerance]
        if matching_highs:
            emit(i, "equal_highs_liquidity_pool", "bearish", bar.high, 0.5,
                 {"tolerance_atr": cfg.equal_level_atr_tolerance, "matching_levels": len(matching_highs)})
        if matching_lows:
            emit(i, "equal_lows_liquidity_pool", "bullish", bar.low, 0.5,
                 {"tolerance_atr": cfg.equal_level_atr_tolerance, "matching_levels": len(matching_lows)})

        # Engulfing candles are descriptive evidence, not stand-alone signals.
        if i >= 1:
            previous = bars[i - 1]
            bullish_engulf = (bar.close > bar.open and previous.close < previous.open and bar.open <= previous.close and bar.close >= previous.open)
            bearish_engulf = (bar.close < bar.open and previous.close > previous.open and bar.open >= previous.close and bar.close <= previous.open)
            if bullish_engulf or bearish_engulf:
                emit(i, "bullish_engulfing" if bullish_engulf else "bearish_engulfing", "bullish" if bullish_engulf else "bearish", None, 0.55, {"previous_body_engulfed": True})

        # Order-block proxy: last opposite candle before a confirmed displacement.
        if body / current_atr >= cfg.displacement_atr_multiple and i >= 1:
            prior = bars[i-1]
            if (bar.close > bar.open and prior.close < prior.open):
                emit(i, "bullish_order_block_proxy", "bullish", prior.low, 0.45,
                     {"source_candle_index": i-1, "confirmation": "following_bullish_displacement"})
            elif (bar.close < bar.open and prior.close > prior.open):
                emit(i, "bearish_order_block_proxy", "bearish", prior.high, 0.45,
                     {"source_candle_index": i-1, "confirmation": "following_bearish_displacement"})

    # Range compression is scaled by local ATR across symbols.
    latest_range_state = "unknown"
    if len(bars) >= cfg.minimum_range_bars and atr[-1] and atr[-1] > 0:
        window = bars[-cfg.minimum_range_bars:]
        normalized_range = (max(x.high for x in window) - min(x.low for x in window)) / atr[-1]
        latest_range_state = "compressed" if normalized_range <= 4.0 else "expanding"
        if latest_range_state == "compressed":
            emit(len(bars)-1, "range_consolidation", "neutral", None, 0.5,
                 {"window_bars": cfg.minimum_range_bars, "range_atr": normalized_range})

    # Coarse rolling context; thresholds are distribution-relative and not
    # hard-coded price/pip constants.
    returns = [0.0] + [(bars[i].close/bars[i-1].close)-1 for i in range(1, len(bars))]
    abs_returns = [abs(x) for x in returns]
    baseline = median(abs_returns[1:]) if len(abs_returns) > 1 else 0.0
    volatility_state = "unknown"
    if baseline > 0 and atr[-1] is not None:
        recent = median(tr[-min(20, len(tr)):])
        volatility_state = "expanding" if recent > baseline * bars[-1].close * 1.5 else (
            "contracting" if recent < baseline * bars[-1].close * 0.65 else "normal"
        )
    highs = [p for _, p in swing_highs[-2:]]
    lows = [p for _, p in swing_lows[-2:]]
    swing_trend = "undetermined"
    if len(highs) == 2 and len(lows) == 2:
        if highs[1] > highs[0] and lows[1] > lows[0]:
            swing_trend = "higher_highs_higher_lows"
        elif highs[1] < highs[0] and lows[1] < lows[0]:
            swing_trend = "lower_highs_lower_lows"
        else:
            swing_trend = "mixed_or_range"

    events.sort(key=lambda e: (e.index, e.kind))
    return {
        "algorithm_id": "causal_multi_structure_ohlc",
        "algorithm_version": "1.0.0",
        "observation_count": len(bars),
        "latest_timestamp": bars[-1].timestamp.isoformat(),
        "structure_direction": structure_direction,
        "swing_trend": swing_trend,
        "volatility_state": volatility_state,
        "range_state": latest_range_state,
        "swing_highs": [{"index": i, "price": p} for i, p in swing_highs],
        "swing_lows": [{"index": i, "price": p} for i, p in swing_lows],
        "events": [asdict(e) for e in events],
        "event_count": len(events),
        "limitations": [
            "OHLC structure is a proxy for market behaviour, not a direct view of dealer inventory or true order flow.",
            "Order-block events are explicitly labelled proxies and require independent validation.",
            "Volume, bid/ask depth, tick sequence and participant identity are not inferred when absent.",
            "A structure event is not a calibrated probability, trade recommendation or execution authorization.",
            "Confirmed swing points are delayed by pivot_right bars to avoid look-ahead bias.",
        ],
    }
