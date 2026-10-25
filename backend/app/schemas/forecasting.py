"""Schemas for forecasting-readiness endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.analysis import ObservationInput


class ForecastingProblemInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_id: str
    version: str = "1.0.0"
    instrument_scope: list[str] = Field(default_factory=list)
    input_timeframe: str = "D1"
    price_basis: str = "close"
    feature_availability_policy: str = "point_in_time"
    prediction_reference: str = "observation_close"
    prediction_horizon: int = Field(default=1, ge=1, le=365)
    target_type: str = "future_return"
    target_units: str = "fraction"
    eligibility_rules: list[str] = Field(
        default_factory=list,
        description=(
            "Rules excluding reference observations from label generation. "
            "Supported form: 'exclude_index:<zero-based observation index>' "
            "(aliases: '<index>', 'exclude:<index>')."
        ),
    )
    label_generation_method: str = "exact_future_observation"
    missing_observation_policy: str = "drop_row"
    required_historical_coverage: int = Field(default=100, ge=1)
    evaluation_protocol: str = "chronological_holdout"
    known_limitations: list[str] = Field(default_factory=list)
    neutral_threshold: float | None = None
    volatility_window: int | None = Field(default=None, ge=2)
    max_features: int = Field(
        default=64,
        ge=1,
        le=256,
        description=(
            "Upper bound on the number of point-in-time features used by models. "
            "The fixed feature set currently contains 11 features, so values above "
            "11 use all available features; smaller values use the first N features "
            "in declared feature order."
        ),
    )


class SplitConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_ratio: float = Field(default=0.6, gt=0.0, lt=1.0)
    validation_ratio: float = Field(default=0.2, gt=0.0, lt=1.0)
    test_ratio: float = Field(default=0.2, gt=0.0, lt=1.0)
    train_end: datetime | None = None
    validation_end: datetime | None = None
    purge: bool = True
    embargo_periods: int = Field(default=0, ge=0)
    min_samples_per_split: int = Field(default=10, ge=1)


class FeatureConstructionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput
    lookback: int = Field(default=20, ge=2, le=200)
    point_in_time_regime_labels: list[str] | None = None
    regime_point_in_time_verified: bool = False


class LabelGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput


class SplitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput
    split: SplitConfigInput = Field(default_factory=SplitConfigInput)


class DatasetBuildRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput
    lookback: int = Field(default=20, ge=2, le=200)
    split: SplitConfigInput = Field(default_factory=SplitConfigInput)
    include_baselines: bool = False


class BaselineRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_targets: list[float]
    test_targets: list[float]
    task_type: str = "regression"


class ForecastingTargetDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    formula: str
    units: str
    description: str


class ForecastingTargetsResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    targets: list[ForecastingTargetDefinition]


class ForecastingProblemValidationResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    errors: list[str]
    spec: dict[str, Any]


class FeatureDatasetResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    feature_rows: list[dict[str, Any]]
    feature_specs: list[dict[str, Any]]
    feature_count: int
    excluded_rows: int


class LabelGenerationResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    labels: list[dict[str, Any]]
    valid_count: int
    total_count: int


class SplitResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    train_indices: list[int]
    validation_indices: list[int]
    test_indices: list[int]
    purged_indices: list[int]
    embargoed_indices: list[int]
    counts: dict[str, int]
    boundaries: dict[str, str | None]
    failed_constraint: str | None = None
    available_required: dict[str, int] = Field(default_factory=dict)


class DatasetBuildResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    manifest: dict[str, Any]
    quality: dict[str, Any]
    split: dict[str, Any]
    feature_count: int
    label_count: int
    valid_label_count: int
    baselines: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class BaselineResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: dict[str, Any]


class ExperimentRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str | None = None
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput
    lookback: int = Field(default=20, ge=2, le=200)
    n_folds: int = Field(default=3, ge=1, le=5)
    min_train_samples: int = Field(default=30, ge=10)
    purge: bool = True
    embargo_periods: int = Field(default=0, ge=0)
    model_families: list[str] = Field(default_factory=list)
    random_seed: int = Field(default=42, ge=0)
    calibration: bool = False
    data_source: str | None = Field(
        default=None,
        description="Declared origin of supplied observations",
    )
    synthetic: bool | None = Field(
        default=None,
        description="Whether supplied observations are synthetic/test data",
    )


class ModelFamiliesResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    families: list[dict[str, Any]]


class ExperimentValidationResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    errors: list[str]
    config: dict[str, Any]


class ExperimentRunResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    status: str
    started_at: str
    completed_at: str
    problem: dict[str, Any]
    dataset_fingerprint: str
    feature_set_version: str
    target_type: str
    task_type: str
    n_observations: int
    n_folds: int
    folds: list[dict[str, Any]]
    models: list[dict[str, Any]]
    comparison: list[dict[str, Any]]
    aggregate: dict[str, Any]
    warnings: list[str]
    limitations: list[str]
    artifact: dict[str, Any]
    data_source: str | None = None
    synthetic: bool | None = None
    data_provenance: dict[str, Any] | None = None
    random_seed: int | None = None
    validation_scheme: str | None = None
    purge: bool | None = None
    embargo_periods: int | None = None
    reproducibility: dict[str, Any] | None = None
    effective_config: dict[str, Any] | None = None
    research_readiness_status: str | None = None
    research_readiness: dict[str, Any] | None = None
    code_version: str | None = None
    git_commit: str | None = None


class HistoricalDatasetRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    observations: list[ObservationInput] | None = None
    instrument: str
    timeframe: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    provider_id: str | None = None
    price_basis: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    problem: ForecastingProblemInput | None = None


class HistoricalDatasetResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    data_source: str
    synthetic: bool
    instrument: str
    timeframe: str
    price_basis: str
    provider_id: str
    observations: list[dict[str, Any]]
    quality: dict[str, Any]
    provenance: dict[str, Any]
    dataset_fingerprint: str
    partial: bool = False


class DataSourceResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    configuration: dict[str, Any]
    connectivity: dict[str, Any]
    contract_status: str


class ResearchReadinessResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    findings: list[dict[str, Any]]
    experiment_validation: dict[str, Any]
    dataset_quality: dict[str, Any] | None = None
    readiness_status: str | None = None
    research_readiness_status: str | None = None
