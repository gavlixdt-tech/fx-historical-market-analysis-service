from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from backend.app.analysis.historical_analogues import retrieve_historical_analogues
from backend.app.analysis.observations import Observation


def _bars(count: int) -> list[Observation]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    values: list[Observation] = []
    previous = 100.0
    for index in range(count):
        change = 0.0012 * math.sin(index / 3.0) + 0.0004 * math.cos(index / 7.0)
        close = previous * math.exp(change)
        open_price = previous
        high = max(open_price, close) * 1.0005
        low = min(open_price, close) * 0.9995
        values.append(Observation(
            timestamp=start + timedelta(minutes=index),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=None,
        ))
        previous = close
    return values


def test_volume_features_are_used_only_with_complete_supported_source_semantics() -> None:
    source_bars = _bars(500)
    bars = [
        Observation(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=1000.0 + 250.0 * (1.0 + math.sin(index / 4.0)),
            volume_kind="broker_tick",
        )
        for index, bar in enumerate(source_bars)
    ]
    result = retrieve_historical_analogues(
        bars,
        instrument="EUR/USD",
        timeframe="M1",
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    assert result["status"] == "completed"
    assert result["volume_context"]["status"] == "AVAILABLE_SOURCE_SPECIFIC"
    assert result["volume_context"]["volume_semantics"] == "broker_tick"
    assert "mean_log_relative_volume" in result["query_features"]
    assert "volume_signed_return_correlation" in result["query_features"]
    assert result["feature_set_version"] == "ohlc-candle-anatomy-volume-aware-v2"


def test_unknown_or_incomplete_volume_is_never_used_as_traded_volume() -> None:
    source_bars = _bars(500)
    unknown = [
        Observation(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=1000.0 + index,
            volume_kind="unknown",
        )
        for index, bar in enumerate(source_bars)
    ]
    result = retrieve_historical_analogues(
        unknown,
        instrument="EUR/USD",
        timeframe="M1",
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    assert result["volume_context"]["status"] == "WITHHELD"
    assert "mean_log_relative_volume" not in result["query_features"]

    incomplete = [
        Observation(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=(1000.0 + index) if index != 250 else None,
            volume_kind="exchange_traded",
        )
        for index, bar in enumerate(source_bars)
    ]
    incomplete_result = retrieve_historical_analogues(
        incomplete,
        instrument="EUR/USD",
        timeframe="M1",
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    assert incomplete_result["volume_context"]["status"] == "WITHHELD"
    assert "mean_log_relative_volume" not in incomplete_result["query_features"]


def test_historical_analogues_exclude_query_and_future_outcome_overlap() -> None:
    bars = _bars(500)
    result = retrieve_historical_analogues(
        bars,
        instrument="EUR/USD",
        timeframe="M1",
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    assert result["status"] == "completed"
    assert result["candidate_window_count"] > 100
    assert result["analogue_count"] >= 5
    query_start = result["query_start_index"]
    selected_intervals: list[tuple[int, int]] = []
    for analogue in result["analogues"]:
        start = next(i for i, bar in enumerate(bars) if bar.timestamp.isoformat() == analogue["window_start"])
        end = next(i for i, bar in enumerate(bars) if bar.timestamp.isoformat() == analogue["window_end"])
        outcome_end = next(i for i, bar in enumerate(bars) if bar.timestamp.isoformat() == analogue["outcome_window_end"])
        assert outcome_end < query_start
        assert 0.0 <= analogue["similarity_score"] <= 1.0
        assert all(not (start <= other_end and outcome_end >= other_start) for other_start, other_end in selected_intervals)
        selected_intervals.append((start, outcome_end))
    assert len(result["outcome_comparison"]) == 5
    assert all(item["analogue_outcomes"]["sample_count"] == result["analogue_count"] for item in result["outcome_comparison"])
    assert all(item["baseline_uses_overlapping_windows"] is True for item in result["outcome_comparison"])


def test_historical_analogues_return_insufficient_data_without_matured_candidates() -> None:
    result = retrieve_historical_analogues(
        _bars(80),
        instrument="EUR/USD",
        timeframe="M1",
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    assert result["status"] in {"insufficient_data", "insufficient_analogues"}
    assert result["analogue_count"] < 5
    assert result["analogues"] == []


def test_historical_analogues_reject_duplicate_or_out_of_order_timestamps() -> None:
    bars = _bars(100)
    bars[10] = Observation(
        timestamp=bars[9].timestamp,
        open=bars[10].open,
        high=bars[10].high,
        low=bars[10].low,
        close=bars[10].close,
    )
    try:
        retrieve_historical_analogues(
            bars,
            instrument="EUR/USD",
            timeframe="M1",
            context_lookback=20,
            outcome_horizons=[1, 3, 5],
            top_k=10,
            minimum_analogue_count=5,
        )
    except ValueError as exc:
        assert "strictly chronological" in str(exc)
    else:
        raise AssertionError("duplicate timestamps must be rejected")
