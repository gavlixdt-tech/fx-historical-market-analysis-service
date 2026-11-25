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
