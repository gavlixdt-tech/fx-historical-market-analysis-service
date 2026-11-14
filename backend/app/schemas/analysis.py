"""Schemas for historical regime and pattern research endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(gt=0, allow_inf_nan=False)
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_observation(self) -> ObservationInput:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, close and low")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= open and close")
        return self


class RegimeConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    return_window: int = Field(default=20, ge=5, le=200)
    volatility_window: int = Field(default=20, ge=5, le=200)
    long_volatility_window: int = Field(default=60, ge=10, le=500)
    trend_threshold: float = Field(default=0.01, ge=0.0)
    high_volatility_threshold: float = Field(default=0.02, ge=0.0)
    low_volatility_threshold: float = Field(default=0.005, ge=0.0)
    direction_consistency_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    range_bound_consistency: float = Field(default=0.3, ge=0.0, le=1.0)
    min_observations: int = Field(default=50, ge=10, le=10000)
    change_point_min_segment: int = Field(default=10, ge=3, le=500)
    change_point_max: int = Field(default=10, ge=1, le=50)
    change_point_penalty: float = Field(default=1.0, ge=0.0)


class RegimeAnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = Field(default=None, max_length=5000)
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    config: RegimeConfigInput = Field(default_factory=RegimeConfigInput)


class RegimeSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_index: int
    end_index: int
    start_timestamp: str
    end_timestamp: str
    observation_count: int
    mean_return: float | None = None
    volatility: float | None = None
    cumulative_return: float | None = None
    max_drawdown: float | None = None
    direction_consistency: float | None = None


class RegimeAnalysisResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str | None = None
    timeframe: str | None = None
    interval_start: str | None = None
    interval_end: str | None = None
    observation_count: int
    feature_set_version: str
    algorithm_id: str
    algorithm_version: str
    config: dict[str, Any]
    regime_timeline: list[dict[str, Any]] = Field(default_factory=list)
    segments: list[RegimeSegment] = Field(default_factory=list)
    change_points: list[str] = Field(default_factory=list)
    regime_proportions: dict[str, float] = Field(default_factory=dict)
    unclassified_count: int = 0
    transition_frequency: float = 0.0
    short_segment_count: int = 0
    sensitivity_agreement: float | None = None
    chronological_validation: dict[str, Any] | None = None
    dataset_fingerprint: str
    data_provenance: dict[str, Any]
    source_quality: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float


class PatternConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_ids: list[
        Literal[
            "volatility_compression_expansion",
            "directional_persistence",
            "reversal_after_large_move",
        ]
    ] = Field(default_factory=lambda: ["volatility_compression_expansion"], min_length=1, max_length=3)
    lookback: int = Field(default=20, ge=5, le=200)
    outcome_horizon: int = Field(default=5, ge=1, le=60)
    overlap_policy: Literal["allow", "min_gap", "no_overlap_outcome"] = "no_overlap_outcome"
    min_gap: int = Field(default=1, ge=1)
    bootstrap_samples: int = Field(default=200, ge=10, le=2000)
    block_size: int = Field(default=5, ge=1, le=50)
    permutations: int = Field(default=200, ge=10, le=2000)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    walk_forward_train_ratio: float = Field(default=0.7, gt=0.0, lt=1.0)
    seed: int = Field(default=42, ge=0)

    @model_validator(mode="after")
    def validate_pattern_ids(self) -> PatternConfigInput:
        if len(set(self.pattern_ids)) != len(self.pattern_ids):
            raise ValueError("pattern_ids must be unique")
        return self


class PatternResearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = Field(default=None, max_length=5000)
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    config: PatternConfigInput = Field(default_factory=PatternConfigInput)


class ResearchSummaryConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    regime: RegimeConfigInput = Field(default_factory=RegimeConfigInput)
    pattern: PatternConfigInput = Field(default_factory=PatternConfigInput)


class ResearchSummaryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = Field(default=None, max_length=5000)
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    config: ResearchSummaryConfigInput = Field(default_factory=ResearchSummaryConfigInput)


class PatternResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_id: str
    pattern_version: str
    event_count: int
    eligible_outcome_count: int
    mean_outcome: float | None = None
    baseline_mean_outcome: float | None = None
    effect_size: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    p_value: float | None = None
    q_value: float | None = None
    significant: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)
    walk_forward: dict[str, Any] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    historical_interval: dict[str, str | None] = Field(default_factory=dict)
    pattern_definition: str
    detection_methodology: str
    outcome_definition: str
    evaluation_horizon: int
    baseline_comparison: dict[str, Any]
    statistical_uncertainty: dict[str, Any]
    data_quality_restrictions: dict[str, Any]
    dataset_fingerprint: str
    warnings: list[str] = Field(default_factory=list)


class PatternResearchResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str | None = None
    timeframe: str | None = None
    observation_count: int
    historical_interval: dict[str, str | None] = Field(default_factory=dict)
    dataset_fingerprint: str
    data_provenance: dict[str, Any]
    source_quality: dict[str, Any] | None = None
    feature_set_version: str
    algorithm_id: str
    algorithm_version: str
    config: dict[str, Any]
    patterns: list[PatternResult] = Field(default_factory=list)
    multiple_testing_method: str
    hypothesis_count: int
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float


class ResearchSummaryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str | None = None
    timeframe: str | None = None
    observation_count: int = 0
    dominant_regime: str | None = None
    regime_share: float | None = None
    volatility_state: str = "unknown"
    trend_state: str = "unknown"
    pattern_id: str | None = None
    pattern_effect_size: float | None = None
    pattern_significance: bool = False
    confidence: float | None = None
    confidence_status: str = "not_calculated"
    narrative: str = ""
    recommendations: list[str] = Field(default_factory=list)
    regime_summary: dict[str, Any] | None = None
    pattern_summary: dict[str, Any] | None = None
    historical_interval: dict[str, str | None] = Field(default_factory=dict)
    dataset_fingerprint: str | None = None
    data_provenance: dict[str, Any] = Field(default_factory=dict)
    source_quality: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class CapabilityDiscoveryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithms: list[str]
    features: list[str]
    patterns: list[str]
    notes: list[str]


class SeasonalityAnalysisRequest(BaseModel):
    """Bounded historical calendar-seasonality research request."""

    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = Field(default=None, max_length=5000)
    instrument: str | None = None
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: Literal["bid", "ask", "midpoint"] | None = None
    limit: int | None = Field(default=None, ge=20, le=5000)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    bucket_types: list[Literal["weekday", "hour_of_day", "month_of_year"]] = Field(
        default_factory=lambda: ["weekday", "hour_of_day", "month_of_year"],
        min_length=1,
        max_length=3,
    )
    minimum_bucket_samples: int = Field(default=20, ge=5, le=500)
    bootstrap_samples: int = Field(default=300, ge=100, le=1000)
    block_size: int = Field(default=5, ge=1, le=50)
    seed: int = Field(default=42, ge=0)
    maximum_gap_multiple: float = Field(default=1.5, ge=1.0, le=4.0)

    @model_validator(mode="after")
    def validate_seasonality_request(self) -> SeasonalityAnalysisRequest:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone identifier") from exc
        if len(set(self.bucket_types)) != len(self.bucket_types):
            raise ValueError("bucket_types must be unique")
        if self.start is not None and (
            self.start.tzinfo is None or self.start.utcoffset() is None
        ):
            raise ValueError("start must include a timezone")
        if self.end is not None and (
            self.end.tzinfo is None or self.end.utcoffset() is None
        ):
            raise ValueError("end must include a timezone")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class SeasonalityBucketResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    bucket_key: str
    bucket_label: str
    observation_count: int
    sample_status: str
    mean_return: float | None = None
    median_return: float | None = None
    positive_return_rate: float | None = None
    realized_volatility: float | None = None
    mean_candle_range_pct: float | None = None
    mean_return_interval_95_lower: float | None = None
    mean_return_interval_95_upper: float | None = None
    difference_from_global_mean: float | None = None


class SeasonalityAnalysisResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str | None = None
    timeframe: str
    timezone: str
    observation_count: int
    return_observation_count: int
    excluded_gap_return_count: int
    interval: dict[str, str | None]
    dataset_fingerprint: str
    analysis_fingerprint: str
    effective_config: dict[str, Any]
    algorithm_id: str
    algorithm_version: str
    global_summary: dict[str, Any]
    buckets: list[SeasonalityBucketResult]
    minimum_bucket_samples: int
    bootstrap: dict[str, Any]
    insufficient_bucket_count: int
    data_provenance: dict[str, Any]
    source_quality: dict[str, Any] | None = None
    forecast_eligible: bool = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float
