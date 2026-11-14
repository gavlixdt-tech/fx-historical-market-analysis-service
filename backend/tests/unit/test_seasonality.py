from datetime import UTC, datetime, timedelta

from backend.app.analysis.observations import Observation
from backend.app.analysis.seasonality import analyze_calendar_seasonality


def observations(count: int = 240) -> list[Observation]:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    rows: list[Observation] = []
    price = 1.0
    for index in range(count):
        price *= 1.0005 if index % 3 else 0.999
        timestamp = start + timedelta(hours=index)
        rows.append(
            Observation(
                timestamp=timestamp,
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
                volume=100.0,
            )
        )
    return rows


def test_calendar_seasonality_groups_by_ending_candle_timezone() -> None:
    result = analyze_calendar_seasonality(
        observations(),
        timeframe="H1",
        timezone_name="Africa/Nairobi",
        bucket_types=["weekday", "hour_of_day"],
        minimum_bucket_samples=2,
        bootstrap_samples=100,
        block_size=3,
        seed=42,
    )

    assert result["timezone"] == "Africa/Nairobi"
    assert result["timeframe"] == "H1"
    assert len(result["buckets"]) == 31
    assert result["global_summary"]["return_observation_count"] == 239
    assert all(bucket["dimension"] in {"weekday", "hour_of_day"} for bucket in result["buckets"])
    assert result["forecast_eligible"] is False


def test_calendar_seasonality_bootstrap_is_deterministic() -> None:
    args = {
        "timeframe": "H1",
        "timezone_name": "UTC",
        "bucket_types": ["hour_of_day"],
        "minimum_bucket_samples": 2,
        "bootstrap_samples": 100,
        "block_size": 3,
        "seed": 7,
    }
    first = analyze_calendar_seasonality(observations(), **args)
    second = analyze_calendar_seasonality(observations(), **args)

    assert first["buckets"] == second["buckets"]


def test_calendar_seasonality_excludes_large_time_gaps() -> None:
    rows = observations(5)
    rows[3] = Observation(
        timestamp=rows[2].timestamp + timedelta(hours=4),
        open=rows[3].open,
        high=rows[3].high,
        low=rows[3].low,
        close=rows[3].close,
    )
    rows[4] = Observation(
        timestamp=rows[3].timestamp + timedelta(hours=1),
        open=rows[4].open,
        high=rows[4].high,
        low=rows[4].low,
        close=rows[4].close,
    )

    result = analyze_calendar_seasonality(
        rows,
        timeframe="H1",
        timezone_name="UTC",
        bucket_types=["hour_of_day"],
        minimum_bucket_samples=2,
        bootstrap_samples=100,
        block_size=2,
        seed=1,
    )

    assert result["global_summary"]["excluded_gap_return_count"] == 1
    assert result["global_summary"]["return_observation_count"] == 3


def test_calendar_seasonality_rejects_unsupported_timeframe() -> None:
    import pytest

    with pytest.raises(ValueError, match="unsupported timeframe"):
        analyze_calendar_seasonality(
            observations(3),
            timeframe="Q1",
            timezone_name="UTC",
            bucket_types=["weekday"],
            minimum_bucket_samples=2,
            bootstrap_samples=100,
            block_size=2,
            seed=1,
        )
