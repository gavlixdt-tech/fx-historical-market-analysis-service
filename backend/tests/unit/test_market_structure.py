from datetime import UTC, datetime, timedelta

import pytest

from backend.app.analysis.market_structure import StructureConfig, analyze_market_structure
from backend.app.analysis.observations import Observation


def make_bars(count: int = 160) -> list[Observation]:
    bars: list[Observation] = []
    price = 1.1
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(count):
        # Deterministic alternating impulses create pivots, sweeps and gaps.
        impulse = (0.0009 if (i // 8) % 2 == 0 else -0.00065)
        if i % 29 == 0:
            impulse *= 3.0
        open_ = price
        close = max(0.5, price + impulse)
        high = max(open_, close) + 0.00025
        low = min(open_, close) - 0.00025
        bars.append(Observation(
            timestamp=start + timedelta(hours=i),
            open=open_, high=high, low=low, close=close, volume=None,
        ))
        price = close
    return bars


def test_market_structure_emits_causal_structure_and_candle_events() -> None:
    result = analyze_market_structure(make_bars())
    kinds = {event["kind"] for event in result["events"]}
    assert result["algorithm_id"] == "causal_multi_structure_ohlc"
    assert result["observation_count"] == 160
    assert "swing_high" in kinds
    assert "swing_low" in kinds
    assert kinds.intersection({
        "break_of_structure", "change_of_character", "bullish_displacement",
        "bearish_displacement", "bullish_fair_value_gap", "bearish_fair_value_gap",
    })
    assert all(0 <= event["strength"] <= 1 for event in result["events"])


def test_confirmed_pivot_records_confirmation_delay() -> None:
    result = analyze_market_structure(make_bars(), StructureConfig(pivot_left=2, pivot_right=4))
    pivots = [event for event in result["events"] if event["kind"] in {"swing_high", "swing_low"}]
    assert pivots
    assert all(event["evidence"]["confirmation_delay_bars"] == 4 for event in pivots)
    assert all(event["index"] >= event["evidence"]["pivot_index"] + 4 for event in pivots)


def test_market_structure_rejects_non_chronological_bars() -> None:
    bars = make_bars(40)
    bars[20] = Observation(
        timestamp=bars[19].timestamp,
        open=bars[20].open, high=bars[20].high, low=bars[20].low, close=bars[20].close,
    )
    with pytest.raises(ValueError, match="strictly chronological"):
        analyze_market_structure(bars)


def test_market_structure_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="insufficient observations"):
        analyze_market_structure(make_bars(10))


def test_equal_high_liquidity_pool_uses_only_previously_confirmed_swings() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Observation] = []
    for i in range(70):
        high = 1.105 if i in {10, 30, 40, 50} else 1.103
        bars.append(Observation(
            timestamp=start + timedelta(hours=i),
            open=1.101,
            high=high,
            low=1.100,
            close=1.102,
            volume=None,
        ))

    result = analyze_market_structure(bars, StructureConfig(pivot_left=2, pivot_right=3))
    pools = [
        event for event in result["events"]
        if event["kind"] == "equal_highs_liquidity_pool" and event["index"] == 40
    ]
    assert pools
    assert pools[0]["evidence"]["matching_levels"] >= 1


@pytest.mark.parametrize("multiple", [0.0, -1.0, float("nan"), float("inf")])
def test_market_structure_rejects_invalid_displacement_threshold(multiple: float) -> None:
    with pytest.raises(ValueError, match="displacement_atr_multiple"):
        analyze_market_structure(make_bars(), StructureConfig(displacement_atr_multiple=multiple))


def test_market_structure_rejects_invalid_range_window() -> None:
    with pytest.raises(ValueError, match="minimum_range_bars"):
        analyze_market_structure(make_bars(), StructureConfig(minimum_range_bars=1))


@pytest.mark.parametrize("volume", [float("nan"), float("inf"), -0.01])
def test_market_structure_rejects_invalid_volume(volume: float) -> None:
    bars = make_bars(40)
    bars[10] = Observation(
        timestamp=bars[10].timestamp,
        open=bars[10].open, high=bars[10].high, low=bars[10].low,
        close=bars[10].close, volume=volume,
    )
    with pytest.raises(ValueError, match="volume must be finite and non-negative"):
        analyze_market_structure(bars)


def test_market_structure_rejects_naive_timestamps() -> None:
    bars = make_bars(40)
    bars[10] = Observation(
        timestamp=bars[10].timestamp.replace(tzinfo=None),
        open=bars[10].open, high=bars[10].high, low=bars[10].low,
        close=bars[10].close,
    )
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        analyze_market_structure(bars)
