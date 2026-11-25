"""Contracts for source-backed historical analogue retrieval and outcome comparison."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.upstream import PriceBasis, Timeframe


class HistoricalAnalogueRequest(BaseModel):
    """Provider-sourced analogue request; caller-supplied candle arrays are not accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=3, max_length=32)
    timeframe: Timeframe
    provider_id: str = Field(min_length=1, max_length=100)
    price_basis: PriceBasis
    end: datetime
    start: datetime | None = None
    limit: int = Field(default=5000, ge=100, le=5000)
    context_lookback: int = Field(default=20, ge=10, le=100)
    outcome_horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20], min_length=1, max_length=5)
    top_k: int = Field(default=25, ge=5, le=50)
    minimum_analogue_count: int = Field(default=10, ge=5, le=50)

    @field_validator("end", "start")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("historical analogue timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> HistoricalAnalogueRequest:
        if self.price_basis == PriceBasis.UNKNOWN:
            raise ValueError("historical analogue search requires an explicit price basis")
        if self.start is not None and self.start >= self.end:
            raise ValueError("start must precede end")
        if self.end > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("end cannot be materially in the future")
        if any(value < 1 or value > 60 for value in self.outcome_horizons):
            raise ValueError("outcome horizons must be between 1 and 60 bars")
        if self.outcome_horizons != sorted(set(self.outcome_horizons)):
            raise ValueError("outcome horizons must be strictly ascending and unique")
        if self.minimum_analogue_count > self.top_k:
            raise ValueError("minimum_analogue_count cannot exceed top_k")
        return self


class HistoricalAnalogueResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str
    timeframe: str
    provider_id: str
    price_basis: str
    observation_count: int
    query_window: dict[str, str]
    query_features: dict[str, float]
    candidate_window_count: int
    analogue_count: int
    top_k: int
    minimum_analogue_count: int
    similarity_method: str
    feature_set_version: str
    analogues: list[dict[str, Any]] = Field(default_factory=list)
    outcome_comparison: list[dict[str, Any]] = Field(default_factory=list)
    dataset_fingerprint: str
    data_provenance: dict[str, Any]
    source_integrity_status: str
    forecast_eligible: bool = False
    confidence: float | None = None
    confidence_calibration_status: str = "NOT_CALIBRATED"
    prediction_authorized: bool = False
    execution_authorized: bool = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float
