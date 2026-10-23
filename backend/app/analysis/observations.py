"""Validation and normalisation of historical observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Observation:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if self.high < self.open or self.high < self.close:
            raise ValueError("high must be >= open and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError("low must be <= open and close")
        if self.close == 0:
            raise ValueError("close must be non-zero")


def coerce_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _to_float(value: object, key: str) -> float:
    if value is None:
        raise ValueError(f"missing required field {key!r}")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        raise ValueError(f"field {key!r} must be numeric")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise ValueError(f"field {key!r} must be numeric")


def from_mapping(raw: dict[str, object]) -> Observation:
    def _float(key: str) -> float:
        return _to_float(raw.get(key), key)

    ts_raw = raw.get("timestamp")
    if ts_raw is None:
        ts_raw = raw.get("open_time")
    if ts_raw is None:
        ts_raw = raw.get("time")
    if ts_raw is None:
        raise ValueError("missing required field 'timestamp'")
    timestamp = coerce_timestamp(ts_raw)

    volume_raw = raw.get("volume")
    volume: float | None = None
    if volume_raw is not None:
        volume = _to_float(volume_raw, "volume")

    return Observation(
        timestamp=timestamp,
        open=_float("open"),
        high=_float("high"),
        low=_float("low"),
        close=_float("close"),
        volume=volume,
    )


def ensure_sorted(observations: list[Observation]) -> list[Observation]:
    ordered = sorted(observations, key=lambda o: o.timestamp)
    for i in range(1, len(ordered)):
        if ordered[i].timestamp == ordered[i - 1].timestamp:
            raise ValueError("duplicate observation timestamps are not allowed")
    return ordered


def validate_minimum(observations: list[Observation], minimum: int) -> None:
    if len(observations) < minimum:
        raise ValueError(
            f"insufficient observations: need at least {minimum}, got {len(observations)}"
        )
