"""Contracts for point-in-time historical replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.forecasting import ForecastingProblemInput


class ReplayObservationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    available_at: datetime
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(gt=0, allow_inf_nan=False)
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_record_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_point_in_time_record(self) -> ReplayObservationInput:
        for field_name in ("timestamp", "available_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.available_at < self.timestamp:
            raise ValueError("available_at cannot precede timestamp")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, close and low")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= open and close")
        return self


class HistoricalReplayRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument: str = Field(min_length=3, max_length=20)
    timeframe: str
    price_basis: Literal["close"] = "close"
    source_dataset_id: str = Field(min_length=1, max_length=200)
    synthetic: bool = False
    observations: list[ReplayObservationInput] = Field(min_length=40, max_length=2000)
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
    def validate_replay_contract(self) -> HistoricalReplayRequest:
        if not self.instrument.strip() or not self.source_dataset_id.strip():
            raise ValueError("instrument and source_dataset_id must not be blank")
        if self.timeframe != self.problem.input_timeframe:
            raise ValueError("timeframe must match problem.input_timeframe")
        if self.instrument not in self.problem.instrument_scope:
            raise ValueError("instrument must be included in problem.instrument_scope")
        if self.validation_mode == "rolling" and self.rolling_window is None:
            raise ValueError("rolling_window is required for rolling validation")
        if self.rolling_window is not None and self.rolling_window < self.min_train_samples:
            raise ValueError("rolling_window must be >= min_train_samples")
        minimum_records = (
            self.lookback
            + self.min_train_samples
            + (2 * self.problem.prediction_horizon)
            + self.embargo_periods
        )
        if len(self.observations) < minimum_records:
            raise ValueError(
                f"at least {minimum_records} observations are required by the "
                "lookback, training, horizon, and embargo settings"
            )
        timestamps = [item.timestamp for item in self.observations]
        available_times = [item.available_at for item in self.observations]
        source_record_ids = [item.source_record_id for item in self.observations]
        if len(set(source_record_ids)) != len(source_record_ids):
            raise ValueError("source_record_id values must be unique")
        if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
            raise ValueError("observations must have unique, increasing timestamps")
        if any(
            right < left for left, right in zip(available_times, available_times[1:], strict=False)
        ):
            raise ValueError("observations must be ordered by nondecreasing available_at")
        if self.final_holdout_start is not None:
            if (
                self.final_holdout_start.tzinfo is None
                or self.final_holdout_start.utcoffset() is None
            ):
                raise ValueError("final_holdout_start must include a timezone")
            if not timestamps[0] < self.final_holdout_start < timestamps[-1]:
                raise ValueError("final_holdout_start must fall inside the observation range")
        if len(set(self.model_families)) != len(self.model_families):
            raise ValueError("model_families must not contain duplicates")
        return self


class HistoricalReplayResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    replay_id: str
    status: str
    instrument: str
    timeframe: str
    target_type: str
    dataset_fingerprint: str
    source_dataset_id: str
    provenance_status: str
    synthetic: bool
    n_observations: int
    n_predictions: int
    validation_mode: str
    predictions: list[dict[str, object]]
    models: list[dict[str, object]]
    robustness: dict[str, object]
    reproducibility: dict[str, object]
    warnings: list[str]
    limitations: list[str]
