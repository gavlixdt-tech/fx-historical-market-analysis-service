"""Request contract for replay runs sourced from the market-data service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.forecasting import ForecastingProblemInput


class HistoricalReplayMarketDataRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument: str = Field(min_length=3, max_length=20)
    timeframe: str
    price_basis: Literal["bid", "ask", "midpoint"]
    provider_id: str = Field(min_length=1, max_length=100)
    source_dataset_id: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime
    limit: int = Field(default=2000, ge=40, le=2000)
    problem: ForecastingProblemInput
    lookback: int = Field(default=20, ge=2, le=200)
    min_train_samples: int = Field(default=30, ge=10, le=1000)
    validation_mode: Literal["expanding", "rolling"] = "expanding"
    rolling_window: int | None = Field(default=None, ge=10, le=1500)
    embargo_periods: int = Field(default=0, ge=0, le=500)
    model_families: list[str] = Field(default_factory=list, max_length=3)
    random_seed: int = Field(default=42, ge=0)
    final_holdout_start: datetime | None = None

    @model_validator(mode="after")
    def validate_request(self) -> HistoricalReplayMarketDataRequest:
        if not self.instrument.strip() or not self.source_dataset_id.strip():
            raise ValueError("instrument and source_dataset_id must not be blank")
        if self.instrument not in self.problem.instrument_scope:
            raise ValueError("instrument must be included in problem.instrument_scope")
        if self.timeframe != self.problem.input_timeframe:
            raise ValueError("timeframe must match problem.input_timeframe")
        for field_name in ("start", "end"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.start >= self.end:
            raise ValueError("start must precede end")
        if self.end.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("end cannot be in the future")
        required_records = (
            self.lookback
            + self.min_train_samples
            + (2 * self.problem.prediction_horizon)
            + self.embargo_periods
        )
        if self.limit < required_records:
            raise ValueError(f"limit must be at least {required_records} for replay settings")
        if self.validation_mode == "rolling" and self.rolling_window is None:
            raise ValueError("rolling_window is required for rolling validation")
        if self.rolling_window is not None and self.rolling_window < self.min_train_samples:
            raise ValueError("rolling_window must be >= min_train_samples")
        if len(set(self.model_families)) != len(self.model_families):
            raise ValueError("model_families must not contain duplicates")
        if self.final_holdout_start is not None and (
            self.final_holdout_start.tzinfo is None
            or self.final_holdout_start.utcoffset() is None
        ):
            raise ValueError("final_holdout_start must include a timezone")
        return self
