"""Contracts for point-in-time historical replay."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.forecasting import ForecastingProblemInput
from backend.app.schemas.instruments import canonicalize_gfx_instrument
from backend.app.schemas.upstream import Timeframe


class ReplaySessionContextInput(BaseModel):
    """Caller-supplied, point-in-time session snapshot; never treated as signed evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["fx-session-context/v1"]
    observed_at: datetime
    available_at: datetime
    active_sessions: list[
        Literal[
            "wellington",
            "sydney",
            "tokyo",
            "hong_kong",
            "singapore",
            "frankfurt",
            "london",
            "new_york",
        ]
    ] = Field(default_factory=list, max_length=8)
    active_open_windows: list[
        Literal["sydney_open", "tokyo_open", "frankfurt_open", "london_open"]
    ] = Field(default_factory=list, max_length=4)
    active_kill_zones: list[
        Literal["ict_asia", "ict_london", "ict_new_york_am", "ict_london_close", "ict_new_york_pm"]
    ] = Field(default_factory=list, max_length=5)
    session_overlap_count: int = Field(ge=0, le=8)
    source_reference: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_session_context(self) -> ReplaySessionContextInput:
        for name in ("observed_at", "available_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"session_context.{name} must include a timezone")
        if self.available_at < self.observed_at:
            raise ValueError("session_context.available_at cannot precede observed_at")
        if len(set(self.active_sessions)) != len(self.active_sessions):
            raise ValueError("session_context.active_sessions must be unique")
        if len(set(self.active_open_windows)) != len(self.active_open_windows):
            raise ValueError("session_context.active_open_windows must be unique")
        if len(set(self.active_kill_zones)) != len(self.active_kill_zones):
            raise ValueError("session_context.active_kill_zones must be unique")
        if self.session_overlap_count != len(self.active_sessions):
            raise ValueError("session_overlap_count must match active_sessions length")
        return self


class ReplayLiquidityLifecycleInput(BaseModel):
    """Caller-supplied lifecycle state with an explicit knowledge-availability time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["liquidity-sweep-lifecycle/v1"]
    observed_at: datetime
    available_at: datetime
    state: Literal[
        "INSUFFICIENT_EVIDENCE_QUALITY",
        "INSUFFICIENT_PRE_SWEEP_HISTORY",
        "NOT_REVERSAL_ELIGIBLE",
        "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT",
        "DISPLACEMENT_CONFIRMED",
        "MIDPOINT_REACHED",
        "MIDPOINT_CONSOLIDATION_CANDIDATE",
        "INVALIDATED",
    ]
    expected_direction: Literal["bullish", "bearish"] | None = None
    source_event_id: str = Field(min_length=1, max_length=200)
    displacement_confirmed_at: datetime | None = None
    midpoint_first_reached_at: datetime | None = None
    consolidation_candidate_at: datetime | None = None
    invalidated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle_context(self) -> ReplayLiquidityLifecycleInput:
        for name in ("observed_at", "available_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"liquidity_lifecycle.{name} must include a timezone")
        if self.available_at < self.observed_at:
            raise ValueError("liquidity_lifecycle.available_at cannot precede observed_at")
        transition_times = (
            ("displacement_confirmed_at", self.displacement_confirmed_at),
            ("midpoint_first_reached_at", self.midpoint_first_reached_at),
            ("consolidation_candidate_at", self.consolidation_candidate_at),
            ("invalidated_at", self.invalidated_at),
        )
        for name, value in transition_times:
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"liquidity_lifecycle.{name} must include a timezone")
                if value > self.observed_at:
                    raise ValueError(f"liquidity_lifecycle.{name} cannot be later than observed_at")
        if (
            self.state
            in {
                "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT",
                "DISPLACEMENT_CONFIRMED",
                "MIDPOINT_REACHED",
                "MIDPOINT_CONSOLIDATION_CANDIDATE",
            }
            and self.expected_direction is None
        ):
            raise ValueError("confirmed lifecycle states require a direction")
        if (
            self.midpoint_first_reached_at is not None
            and self.displacement_confirmed_at is None
        ):
            raise ValueError("midpoint_first_reached_at requires displacement_confirmed_at")
        if (
            self.consolidation_candidate_at is not None
            and self.midpoint_first_reached_at is None
        ):
            raise ValueError("consolidation_candidate_at requires midpoint_first_reached_at")
        if (
            self.midpoint_first_reached_at is not None
            and self.displacement_confirmed_at is not None
            and self.midpoint_first_reached_at < self.displacement_confirmed_at
        ):
            raise ValueError("midpoint_first_reached_at cannot precede displacement_confirmed_at")
        if (
            self.consolidation_candidate_at is not None
            and self.midpoint_first_reached_at is not None
            and self.consolidation_candidate_at < self.midpoint_first_reached_at
        ):
            raise ValueError("consolidation_candidate_at cannot precede midpoint_first_reached_at")
        return self


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
    session_context: ReplaySessionContextInput | None = None
    liquidity_lifecycle: ReplayLiquidityLifecycleInput | None = None

    @model_validator(mode="after")
    def validate_point_in_time_record(self) -> ReplayObservationInput:
        for field_name in ("timestamp", "available_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.available_at < self.timestamp:
            raise ValueError("available_at cannot precede timestamp")
        contexts = (
            ("session_context", self.session_context),
            ("liquidity_lifecycle", self.liquidity_lifecycle),
        )
        for name, context in contexts:
            if context is not None and context.observed_at > self.timestamp:
                raise ValueError(f"{name}.observed_at cannot be later than the candle timestamp")
        now = datetime.now(UTC)
        if self.timestamp.astimezone(UTC) > now or self.available_at.astimezone(UTC) > now:
            raise ValueError(
                "historical observation and availability timestamps cannot be in the future"
            )
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
        canonical_instrument = canonicalize_gfx_instrument(self.instrument)
        if not self.synthetic and canonical_instrument is None:
            raise ValueError("instrument is outside the approved GFX instrument scope")
        if self.timeframe not in {timeframe.value for timeframe in Timeframe}:
            raise ValueError("timeframe is not supported")
        if self.timeframe != self.problem.input_timeframe:
            raise ValueError("timeframe must match problem.input_timeframe")
        canonical_scope = {
            canonicalize_gfx_instrument(item) or item for item in self.problem.instrument_scope
        }
        expected_scope_value = canonical_instrument or self.instrument
        if expected_scope_value not in canonical_scope:
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
