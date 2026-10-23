"""Schemas for historical regime and pattern research endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ObservationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


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

    observations: list[ObservationInput] | None = None
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
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    duration_ms: float


class PatternConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_ids: list[str] = Field(default_factory=lambda: ["volatility_compression_expansion"])
    lookback: int = Field(default=20, ge=5, le=200)
    outcome_horizon: int = Field(default=5, ge=1, le=60)
    overlap_policy: str = Field(default="no_overlap_outcome")
    min_gap: int = Field(default=1, ge=1)
    bootstrap_samples: int = Field(default=200, ge=10, le=2000)
    block_size: int = Field(default=5, ge=1, le=50)
    permutations: int = Field(default=200, ge=10, le=2000)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    walk_forward_train_ratio: float = Field(default=0.7, gt=0.0, lt=1.0)
    seed: int = Field(default=42)


class PatternResearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    config: PatternConfigInput = Field(default_factory=PatternConfigInput)


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
    warnings: list[str] = Field(default_factory=list)


class PatternResearchResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    analysis_id: str
    instrument: str | None = None
    timeframe: str | None = None
    observation_count: int
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


class CapabilityDiscoveryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithms: list[str]
    features: list[str]
    patterns: list[str]
    notes: list[str]
