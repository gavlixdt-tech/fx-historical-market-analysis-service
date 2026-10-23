"""Data-quality and integrity checks for upstream historical market data."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

_TIMEFRAME_DELTAS = {
    "M1": timedelta(minutes=1),
    "M5": timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D1": timedelta(days=1),
    "W1": timedelta(weeks=1),
}


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        value = float(value)
    elif isinstance(value, Decimal):
        value = float(value)
    elif isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(value):
        return None
    return value


def _parse_ts(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_weekend_gap(start, end, delta):
    if delta < timedelta(days=1):
        return False
    if start.weekday() >= 4 and end.weekday() <= 1 and (end - start).days >= 2:
        return True
    return False


def validate_historical_payload(
    data,
    *,
    expected_instrument=None,
    expected_timeframe=None,
    expected_price_basis=None,
):
    blocking = []
    warnings = []
    info = []

    timeframe = str(data.timeframe)
    price_basis = str(data.price_basis)
    instrument = data.canonical_instrument

    if expected_instrument and instrument != expected_instrument:
        blocking.append(
            f"unexpected instrument: expected {expected_instrument!r}, got {instrument!r}"
        )
    if expected_timeframe and timeframe != expected_timeframe:
        blocking.append(f"unexpected timeframe: expected {expected_timeframe!r}, got {timeframe!r}")
    if expected_price_basis and price_basis != expected_price_basis:
        blocking.append(
            f"unexpected price basis: expected {expected_price_basis!r}, got {price_basis!r}"
        )

    delta = _TIMEFRAME_DELTAS.get(timeframe)
    if delta is None:
        warnings.append(f"unknown timeframe {timeframe!r}; gap detection skipped")

    candles = list(data.candles)
    if not candles:
        warnings.append("no candles returned")

    requested_start = _parse_ts(data.requested_start) or _parse_ts(data.coverage.requested_start)
    requested_end = _parse_ts(data.requested_end) or _parse_ts(data.coverage.requested_end)
    actual_start = _parse_ts(data.effective_start) or _parse_ts(data.coverage.actual_start)
    actual_end = _parse_ts(data.effective_end) or _parse_ts(data.coverage.actual_end)

    if actual_start is None and candles:
        actual_start = _parse_ts(candles[0].open_time)
    if actual_end is None and candles:
        actual_end = _parse_ts(candles[-1].open_time)

    partial = False
    if requested_start is not None and actual_start is not None and actual_start > requested_start:
        partial = True
        warnings.append("partial coverage at start of requested range")
    if requested_end is not None and actual_end is not None and actual_end < requested_end:
        partial = True
        warnings.append("partial coverage at end of requested range")

    parsed_rows = []
    for candle in candles:
        ts = _parse_ts(candle.open_time)
        if ts is None:
            blocking.append(f"unparseable candle timestamp: {candle.open_time!r}")
            continue
        parsed_rows.append((ts, candle))

    out_of_order = 0
    for i in range(1, len(parsed_rows)):
        if parsed_rows[i][0] < parsed_rows[i - 1][0]:
            out_of_order += 1
    if out_of_order:
        blocking.append(f"{out_of_order} out-of-order candle(s) detected")

    seen = {}
    duplicate_count = 0
    conflicting_duplicates = 0
    for ts, candle in parsed_rows:
        key = ts.isoformat()
        if key in seen:
            duplicate_count += 1
            prev = seen[key]
            if (
                _to_float(prev.open) != _to_float(candle.open)
                or _to_float(prev.high) != _to_float(candle.high)
                or _to_float(prev.low) != _to_float(candle.low)
                or _to_float(prev.close) != _to_float(candle.close)
            ):
                conflicting_duplicates += 1
        else:
            seen[key] = candle
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate timestamp(s) detected")
    if conflicting_duplicates:
        blocking.append(f"{conflicting_duplicates} conflicting duplicate candle(s) detected")

    invalid_ohlc = 0
    negative_prices = 0
    non_finite = 0
    volume_issues = 0
    for _ts, candle in parsed_rows:
        o = _to_float(candle.open)
        h = _to_float(candle.high)
        lo = _to_float(candle.low)
        c = _to_float(candle.close)
        v = _to_float(candle.volume) if candle.volume is not None else None

        if o is None or h is None or lo is None or c is None:
            if (
                candle.open is not None
                or candle.high is not None
                or candle.low is not None
                or candle.close is not None
            ):
                non_finite += 1
            continue
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            negative_prices += 1
        if h < lo:
            invalid_ohlc += 1
        if h < o or h < c:
            invalid_ohlc += 1
        if lo > o or lo > c:
            invalid_ohlc += 1
        if v is not None and v < 0:
            volume_issues += 1

    if non_finite:
        blocking.append(f"{non_finite} non-finite or unparseable OHLC value(s)")
    if negative_prices:
        blocking.append(f"{negative_prices} candle(s) with non-positive prices")
    if invalid_ohlc:
        blocking.append(f"{invalid_ohlc} candle(s) with inconsistent high/low/open/close")
    if volume_issues:
        warnings.append(f"{volume_issues} candle(s) with negative volume")

    precision_issues = 0
    for ts, _ in parsed_rows:
        if ts.microsecond not in (0,):
            precision_issues += 1
    if precision_issues:
        info.append(f"{precision_issues} candle(s) with sub-second timestamp precision")

    unique_sorted = sorted({ts for ts, _ in parsed_rows})
    gaps = []
    missing_intervals = 0
    if delta is not None and len(unique_sorted) >= 2:
        for i in range(1, len(unique_sorted)):
            diff = unique_sorted[i] - unique_sorted[i - 1]
            if diff > delta:
                try:
                    count = int(diff / delta) - 1
                except (ZeroDivisionError, ValueError):
                    count = 0
                if count < 0:
                    count = 0
                missing_intervals += count
                expected = _is_weekend_gap(unique_sorted[i - 1], unique_sorted[i], delta)
                gaps.append(
                    {
                        "start": unique_sorted[i - 1].isoformat(),
                        "end": unique_sorted[i].isoformat(),
                        "missing_intervals": count,
                        "expected_non_trading_interval": expected,
                        "reason": "weekend_or_session_gap"
                        if expected
                        else "possible_missing_candle",
                    }
                )
    if missing_intervals:
        if any(not g["expected_non_trading_interval"] for g in gaps):
            warnings.append(f"{missing_intervals} potentially missing candle interval(s) detected")
        else:
            info.append(f"{missing_intervals} interval(s) fall on expected non-trading gaps")

    if requested_start is not None and actual_start is not None and actual_start > requested_start:
        gaps.insert(
            0,
            {
                "start": requested_start.isoformat(),
                "end": actual_start.isoformat(),
                "missing_intervals": None,
                "expected_non_trading_interval": False,
                "reason": "missing_data_at_start",
            },
        )
    if requested_end is not None and actual_end is not None and actual_end < requested_end:
        gaps.append(
            {
                "start": actual_end.isoformat(),
                "end": requested_end.isoformat(),
                "missing_intervals": None,
                "expected_non_trading_interval": False,
                "reason": "missing_data_at_end",
            }
        )

    coverage = data.coverage
    if coverage.status and str(coverage.status).lower() not in {"complete", "ok"}:
        warnings.append(f"upstream coverage status: {coverage.status}")
    if coverage.rejected_count:
        warnings.append(f"upstream rejected {coverage.rejected_count} candle(s)")
    if coverage.duplicate_count:
        warnings.append(f"upstream reported {coverage.duplicate_count} duplicate(s)")

    valid = len(blocking) == 0

    return {
        "valid": valid,
        "blocking_errors": blocking,
        "warnings": warnings,
        "info": info,
        "row_count": len(candles),
        "unique_timestamp_count": len(unique_sorted),
        "duplicate_count": duplicate_count,
        "conflicting_duplicate_count": conflicting_duplicates,
        "out_of_order_count": out_of_order,
        "missing_interval_count": missing_intervals,
        "invalid_ohlc_count": invalid_ohlc,
        "non_finite_count": non_finite,
        "negative_price_count": negative_prices,
        "volume_issue_count": volume_issues,
        "precision_issue_count": precision_issues,
        "partial": partial,
        "gaps": gaps,
        "coverage": {
            "requested_start": requested_start.isoformat() if requested_start else None,
            "requested_end": requested_end.isoformat() if requested_end else None,
            "actual_start": actual_start.isoformat() if actual_start else None,
            "actual_end": actual_end.isoformat() if actual_end else None,
            "upstream_status": coverage.status,
            "expected_intervals": coverage.expected_intervals,
            "returned_count": coverage.returned_count,
            "valid_count": coverage.valid_count,
            "rejected_count": coverage.rejected_count,
            "duplicate_count": coverage.duplicate_count,
            "complete": coverage.complete,
            "provider_limited": coverage.provider_limited,
            "notes": coverage.notes,
        },
        "source_limitations": list(data.limitations),
    }
