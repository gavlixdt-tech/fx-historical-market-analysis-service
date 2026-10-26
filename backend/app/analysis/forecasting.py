"""Forecasting-readiness primitives (no model training)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.analysis.observations import Observation

SUPPORTED_TARGET_TYPES = (
    "future_return",
    "log_return",
    "direction",
    "realized_volatility",
)

ALGORITHM_VERSION = "1.0.0"
DATASET_SCHEMA_VERSION = "1.0.0"
FEATURE_SET_VERSION = "1.0.0"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: str
    definition: str
    required_fields: tuple[str, ...]
    lookback: int
    earliest_availability: str
    missing_behavior: str
    transformation: str
    available_at_prediction_time: bool


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "lag_return_1",
        FEATURE_SET_VERSION,
        "Simple return over one observation.",
        ("close",),
        2,
        "after first observation",
        "None when unavailable",
        "(P_t/P_{t-1})-1",
        True,
    ),
    FeatureSpec(
        "rolling_mean_return",
        FEATURE_SET_VERSION,
        "Mean simple return over the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "None if any required return missing",
        "mean of simple returns",
        True,
    ),
    FeatureSpec(
        "rolling_std_return",
        FEATURE_SET_VERSION,
        "Sample standard deviation of simple returns over the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "None if any required return missing",
        "sample std of simple returns",
        True,
    ),
    FeatureSpec(
        "historical_volatility",
        FEATURE_SET_VERSION,
        "Rolling standard deviation of simple returns used as a historical volatility proxy.",
        ("close",),
        20,
        "after lookback observations",
        "None if unavailable",
        "rolling_std_return",
        True,
    ),
    FeatureSpec(
        "cumulative_return",
        FEATURE_SET_VERSION,
        "Compounded return over the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "None if any required return missing",
        "product(1+r)-1",
        True,
    ),
    FeatureSpec(
        "direction_consistency",
        FEATURE_SET_VERSION,
        "Mean sign of returns over the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "None if any required return missing",
        "mean(sign(r))",
        True,
    ),
    FeatureSpec(
        "max_drawdown",
        FEATURE_SET_VERSION,
        "Maximum drawdown of closes over the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "0.0 when insufficient",
        "max peak-to-trough decline",
        True,
    ),
    FeatureSpec(
        "candle_range_pct",
        FEATURE_SET_VERSION,
        "Candle range relative to close.",
        ("high", "low", "close"),
        1,
        "immediate",
        "None when close is zero",
        "(high-low)/close",
        True,
    ),
    FeatureSpec(
        "candle_body_ratio",
        FEATURE_SET_VERSION,
        "Absolute candle body relative to range.",
        ("open", "high", "low", "close"),
        1,
        "immediate",
        "None when range is zero",
        "abs(close-open)/(high-low)",
        True,
    ),
    FeatureSpec(
        "data_quality_missing_count",
        FEATURE_SET_VERSION,
        "Count of missing returns in the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "0",
        "count of None returns",
        True,
    ),
    FeatureSpec(
        "coverage_ratio",
        FEATURE_SET_VERSION,
        "Share of non-missing returns in the lookback window ending at t.",
        ("close",),
        20,
        "after lookback observations",
        "0.0 when no observations",
        "valid returns / window",
        True,
    ),
    FeatureSpec(
        "observation_count_to_date",
        FEATURE_SET_VERSION,
        "Number of source observations available through t.",
        ("timestamp",),
        1,
        "immediate",
        "exact count",
        "i+1",
        True,
    ),
)


FORECAST_FEATURE_NAMES: tuple[str, ...] = (
    "lag_return_1",
    "rolling_mean_return",
    "rolling_std_return",
    "historical_volatility",
    "cumulative_return",
    "direction_consistency",
    "max_drawdown",
    "candle_range_pct",
    "candle_body_ratio",
    "data_quality_missing_count",
    "coverage_ratio",
)


def _parse_eligibility_index(rule: str) -> int:
    if not isinstance(rule, str) or not rule.strip():
        raise ValueError("eligibility rule must be a non-empty string")
    text = rule.strip()
    if ":" in text:
        prefix, value = text.split(":", 1)
        prefix = prefix.strip().lower().replace("-", "_")
        if prefix not in {
            "exclude_index",
            "exclude_reference_index",
            "exclude",
            "index",
        }:
            raise ValueError("unsupported eligibility rule type; expected exclude_index:<index>")
    else:
        value = text
    value = value.strip()
    try:
        index = int(value)
    except ValueError as exc:
        raise ValueError("eligibility rule index must be an integer") from exc
    if index < 0:
        raise ValueError("eligibility rule index must be non-negative")
    return index


def validate_eligibility_rules(rules: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for rule in rules:
        try:
            _parse_eligibility_index(rule)
        except ValueError as exc:
            errors.append(f"invalid eligibility rule {rule!r}: {exc}")
    return errors


def resolve_eligibility_exclusions(rules: Sequence[str], observation_count: int) -> set[int]:
    if observation_count < 0:
        raise ValueError("observation_count must be non-negative")
    excluded: set[int] = set()
    for rule in rules:
        index = _parse_eligibility_index(rule)
        if index >= observation_count:
            raise ValueError(
                f"eligibility rule index {index} is out of range for "
                f"{observation_count} observations"
            )
        excluded.add(index)
    return excluded


@dataclass(frozen=True)
class ForecastingProblemSpec:
    problem_id: str
    version: str = "1.0.0"
    instrument_scope: tuple[str, ...] = ()
    input_timeframe: str = "D1"
    price_basis: str = "close"
    feature_availability_policy: str = "point_in_time"
    prediction_reference: str = "observation_close"
    prediction_horizon: int = 1
    target_type: str = "future_return"
    target_units: str = "fraction"
    eligibility_rules: tuple[str, ...] = ()
    label_generation_method: str = "exact_future_observation"
    missing_observation_policy: str = "drop_row"
    required_historical_coverage: int = 100
    evaluation_protocol: str = "chronological_holdout"
    known_limitations: tuple[str, ...] = ()
    neutral_threshold: float | None = None
    volatility_window: int | None = None
    max_features: int = 64

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.problem_id:
            errors.append("problem_id is required")
        if self.prediction_horizon < 1 or self.prediction_horizon > 365:
            errors.append("prediction_horizon must be between 1 and 365")
        if self.target_type not in SUPPORTED_TARGET_TYPES:
            errors.append(f"unsupported target_type: {self.target_type}")
        if self.input_timeframe not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"}:
            errors.append(f"unsupported input_timeframe: {self.input_timeframe}")
        if self.price_basis not in {"bid", "ask", "mid", "close"}:
            errors.append(f"unsupported price_basis: {self.price_basis}")
        if self.feature_availability_policy != "point_in_time":
            errors.append("feature_availability_policy must be 'point_in_time'")
        if self.label_generation_method not in {
            "exact_future_observation",
            "next_eligible_observation",
        }:
            errors.append("unsupported label_generation_method")
        if self.required_historical_coverage < 1:
            errors.append("required_historical_coverage must be positive")
        if self.max_features < 1 or self.max_features > 256:
            errors.append("max_features must be between 1 and 256")
        if self.target_type == "direction" and self.neutral_threshold is None:
            errors.append("neutral_threshold is required for direction targets")
        if self.target_type == "realized_volatility" and (
            self.volatility_window is None or self.volatility_window < 2
        ):
            errors.append("volatility_window >= 2 is required for realized_volatility targets")
        if self.eligibility_rules:
            errors.extend(validate_eligibility_rules(self.eligibility_rules))
        return errors


@dataclass(frozen=True)
class TargetLabel:
    reference_index: int
    reference_timestamp: str
    future_index: int | None
    future_timestamp: str | None
    status: str
    reason: str | None
    value: float | None
    target_type: str


def _simple_returns(closes: Sequence[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev == 0:
            out.append(None)
        else:
            out.append((closes[i] - prev) / prev)
    return out


def generate_labels(
    observations: Sequence[Observation],
    spec: ForecastingProblemSpec,
    excluded_indices: set[int] | None = None,
) -> list[TargetLabel]:
    """Generate deterministic historical labels without future leakage in features."""
    excluded = set(excluded_indices or ())
    excluded.update(resolve_eligibility_exclusions(spec.eligibility_rules, len(observations)))
    closes = [o.close for o in observations]
    n = len(observations)
    horizon = spec.prediction_horizon
    out: list[TargetLabel] = []
    for i in range(n):
        ref_ts = observations[i].timestamp.isoformat()
        if i in excluded:
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=None,
                    future_timestamp=None,
                    status="excluded",
                    reason="excluded by documented eligibility rule",
                    value=None,
                    target_type=spec.target_type,
                )
            )
            continue
        j = i + horizon
        if j >= n:
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=None,
                    future_timestamp=None,
                    status="missing_future_horizon",
                    reason="full required future window does not exist",
                    value=None,
                    target_type=spec.target_type,
                )
            )
            continue
        ref_close = closes[i]
        fut_close = closes[j]
        if ref_close == 0:
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=j,
                    future_timestamp=observations[j].timestamp.isoformat(),
                    status="invalid_source_observation",
                    reason="reference close is zero",
                    value=None,
                    target_type=spec.target_type,
                )
            )
            continue
        if ref_close < 0 or fut_close <= 0:
            status = "invalid_source_observation"
            reason = "non-positive price encountered"
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=j,
                    future_timestamp=observations[j].timestamp.isoformat(),
                    status=status,
                    reason=reason,
                    value=None,
                    target_type=spec.target_type,
                )
            )
            continue
        if spec.target_type in {"future_return", "log_return", "direction"}:
            if spec.target_type == "future_return":
                value = fut_close / ref_close - 1.0
            elif spec.target_type == "log_return":
                value = math.log(fut_close / ref_close)
            else:
                ret = fut_close / ref_close - 1.0
                threshold = spec.neutral_threshold or 0.0
                if ret > threshold:
                    value = 1.0  # encoded up
                elif ret < -threshold:
                    value = -1.0  # encoded down
                else:
                    value = 0.0  # neutral
            # For direction we store encoded numeric; consumers map to labels.
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=j,
                    future_timestamp=observations[j].timestamp.isoformat(),
                    status="valid",
                    reason=None,
                    value=value,
                    target_type=spec.target_type,
                )
            )
        elif spec.target_type == "realized_volatility":
            window = spec.volatility_window or horizon
            # The volatility window must be contiguous over the exact future
            # horizon. Missing or invalid returns are not filtered out to
            # manufacture a label.
            future_closes = closes[i : j + 1]
            rets = _simple_returns(future_closes)
            returns = rets[1:]
            if len(returns) != horizon or any(r is None for r in returns):
                out.append(
                    TargetLabel(
                        reference_index=i,
                        reference_timestamp=ref_ts,
                        future_index=j,
                        future_timestamp=observations[j].timestamp.isoformat(),
                        status="invalid_source_observation",
                        reason="non-contiguous or invalid future observations for volatility",
                        value=None,
                        target_type=spec.target_type,
                    )
                )
                continue
            if window > len(returns) or len(returns) < 2:
                out.append(
                    TargetLabel(
                        reference_index=i,
                        reference_timestamp=ref_ts,
                        future_index=j,
                        future_timestamp=observations[j].timestamp.isoformat(),
                        status="insufficient_observations",
                        reason="insufficient future observations for volatility",
                        value=None,
                        target_type=spec.target_type,
                    )
                )
                continue
            chunk = returns[-window:]
            if len(chunk) < 2:
                out.append(
                    TargetLabel(
                        reference_index=i,
                        reference_timestamp=ref_ts,
                        future_index=j,
                        future_timestamp=observations[j].timestamp.isoformat(),
                        status="insufficient_observations",
                        reason="insufficient future observations for volatility",
                        value=None,
                        target_type=spec.target_type,
                    )
                )
                continue
            valid_chunk = [r for r in chunk if r is not None]
            mean = sum(valid_chunk) / len(valid_chunk)
            var = sum((r - mean) ** 2 for r in valid_chunk) / (len(valid_chunk) - 1)
            vol = math.sqrt(var) if var >= 0 else None
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=j,
                    future_timestamp=observations[j].timestamp.isoformat(),
                    status="valid",
                    reason=None,
                    value=vol,
                    target_type=spec.target_type,
                )
            )
        else:
            out.append(
                TargetLabel(
                    reference_index=i,
                    reference_timestamp=ref_ts,
                    future_index=j,
                    future_timestamp=observations[j].timestamp.isoformat(),
                    status="excluded",
                    reason="unsupported target type",
                    value=None,
                    target_type=spec.target_type,
                )
            )
    return out


def build_point_in_time_features(
    observations: Sequence[Observation],
    spec: ForecastingProblemSpec,
    lookback: int = 20,
    point_in_time_regime_labels: Sequence[str] | None = None,
    regime_point_in_time_verified: bool = False,
) -> list[dict[str, Any] | None]:
    """Build feature rows using only observations available at each reference timestamp."""
    closes = [o.close for o in observations]
    returns = _simple_returns(closes)
    out: list[dict[str, Any] | None] = []
    for i in range(len(observations)):
        if i + 1 < lookback:
            out.append(None)
            continue
        window_returns = returns[i - lookback + 1 : i + 1]
        nums = [r for r in window_returns if r is not None]
        # rolling stats require full window when strict
        full = len(nums) == lookback and all(r is not None for r in window_returns)
        row: dict[str, Any] = {
            "reference_index": i,
            "reference_timestamp": observations[i].timestamp.isoformat(),
            "lookback": lookback,
        }
        # lagged return
        if i >= 1 and closes[i - 1] != 0:
            row["lag_return_1"] = (closes[i] - closes[i - 1]) / closes[i - 1]
        else:
            row["lag_return_1"] = None
        if full:
            mean = sum(nums) / len(nums)
            var = sum((r - mean) ** 2 for r in nums) / (len(nums) - 1)
            row["rolling_mean_return"] = mean
            row["rolling_std_return"] = math.sqrt(var) if var >= 0 else None
            row["historical_volatility"] = row["rolling_std_return"]
            # cumulative
            product = 1.0
            for r in nums:
                product *= 1.0 + r
            row["cumulative_return"] = product - 1.0
            # direction consistency
            signs = [1.0 if (r or 0) > 0 else (-1.0 if (r or 0) < 0 else 0.0) for r in nums]
            row["direction_consistency"] = sum(signs) / len(signs)
        else:
            row["rolling_mean_return"] = None
            row["rolling_std_return"] = None
            row["historical_volatility"] = None
            row["cumulative_return"] = None
            row["direction_consistency"] = None
        # max drawdown over lookback closes
        chunk_closes = closes[i - lookback + 1 : i + 1]
        peak = chunk_closes[0]
        max_dd = 0.0
        for c in chunk_closes:
            if c > peak:
                peak = c
            if peak != 0:
                dd = (peak - c) / peak
                if dd > max_dd:
                    max_dd = dd
        row["max_drawdown"] = max_dd
        # candle features
        o = observations[i]
        row["candle_range_pct"] = (o.high - o.low) / o.close if o.close != 0 else None
        rng = o.high - o.low
        row["candle_body_ratio"] = abs(o.close - o.open) / rng if rng != 0 else None
        # data quality
        row["data_quality_missing_count"] = sum(1 for r in window_returns if r is None)
        row["coverage_ratio"] = len(nums) / lookback if lookback > 0 else 0.0
        row["observation_count_to_date"] = i + 1
        # metadata
        row["instrument"] = None
        row["timeframe"] = spec.input_timeframe
        # retrospective outputs are not silently treated as real-time features
        if point_in_time_regime_labels is not None:
            if not regime_point_in_time_verified:
                raise ValueError(
                    "retrospective regime labels cannot be used as point-in-time features "
                    "unless a strictly point-in-time reconstruction is verified"
                )
            if len(point_in_time_regime_labels) != len(observations):
                raise ValueError("regime label count must match observations")
            row["regime_label"] = point_in_time_regime_labels[i]
        out.append(row)
    return out


@dataclass(frozen=True)
class SplitConfig:
    train_ratio: float = 0.6
    validation_ratio: float = 0.2
    test_ratio: float = 0.2
    train_end: datetime | None = None
    validation_end: datetime | None = None
    purge: bool = True
    embargo_periods: int = 0
    min_samples_per_split: int = 10


@dataclass(frozen=True)
class SplitResult:
    status: str
    train_indices: list[int]
    validation_indices: list[int]
    test_indices: list[int]
    purged_indices: list[int]
    embargoed_indices: list[int]
    train_start: str | None
    train_end: str | None
    validation_start: str | None
    validation_end: str | None
    test_start: str | None
    test_end: str | None
    counts: dict[str, int]
    failed_constraint: str | None
    available_required: dict[str, int]
    config: dict[str, Any]
    algorithm_version: str = ALGORITHM_VERSION


def chronological_split(
    reference_timestamps: Sequence[datetime],
    config: SplitConfig,
    outcome_end_timestamps: Sequence[datetime] | None = None,
) -> SplitResult:
    n = len(reference_timestamps)
    ts = list(reference_timestamps)
    # determine boundaries by index
    if config.train_end is not None or config.validation_end is not None:
        train_end_dt = config.train_end
        val_end_dt = config.validation_end
        train_idx: list[int] = []
        val_idx: list[int] = []
        test_idx: list[int] = []
        for i, t in enumerate(ts):
            if train_end_dt is not None and t < train_end_dt:
                train_idx.append(i)
            elif val_end_dt is not None and t < val_end_dt:
                val_idx.append(i)
            else:
                test_idx.append(i)
    else:
        train_n = int(n * config.train_ratio)
        val_n = int(n * config.validation_ratio)
        if train_n < 1:
            train_n = 1
        if train_n + val_n >= n:
            val_n = max(1, n - train_n - 1)
        train_idx = list(range(0, train_n))
        val_idx = list(range(train_n, train_n + val_n))
        test_idx = list(range(train_n + val_n, n))

    # embargo: drop tail of train within embargo_periods (by index spacing)
    purged: list[int] = []
    embargoed: list[int] = []
    if config.purge and outcome_end_timestamps is not None:
        # validation/test start timestamp
        boundary_candidates = []
        if val_idx:
            boundary_candidates.append(ts[val_idx[0]])
        if test_idx:
            boundary_candidates.append(ts[test_idx[0]])
        boundary_start = min(boundary_candidates) if boundary_candidates else None
        if boundary_start is not None:
            new_train: list[int] = []
            for i in train_idx:
                end_ts = outcome_end_timestamps[i]
                if end_ts >= boundary_start:
                    purged.append(i)
                else:
                    new_train.append(i)
            train_idx = new_train

    if config.embargo_periods and config.embargo_periods > 0 and train_idx:
        # convert periods to a count using observed spacing; drop last N train samples
        # before the next boundary to create an explicit gap.
        n_embargo = min(config.embargo_periods, len(train_idx))
        if n_embargo > 0:
            embargoed.extend(train_idx[-n_embargo:])
            train_idx = train_idx[:-n_embargo]

    # insufficient data check
    failed: str | None = None
    avail_req = {
        "train_available": len(train_idx),
        "train_required": config.min_samples_per_split,
        "validation_available": len(val_idx),
        "validation_required": config.min_samples_per_split,
        "test_available": len(test_idx),
        "test_required": config.min_samples_per_split,
    }
    if len(train_idx) < config.min_samples_per_split:
        failed = "train"
    elif len(val_idx) < config.min_samples_per_split:
        failed = "validation"
    elif len(test_idx) < config.min_samples_per_split:
        failed = "test"

    status = "insufficient_data" if failed else "completed"

    def _iso(i: int | None) -> str | None:
        if i is None or i >= n:
            return None
        return ts[i].isoformat()

    train_start = ts[train_idx[0]].isoformat() if train_idx else None
    train_end = ts[train_idx[-1]].isoformat() if train_idx else None
    val_start = ts[val_idx[0]].isoformat() if val_idx else None
    val_end = ts[val_idx[-1]].isoformat() if val_idx else None
    test_start = ts[test_idx[0]].isoformat() if test_idx else None
    test_end = ts[test_idx[-1]].isoformat() if test_idx else None

    return SplitResult(
        status=status,
        train_indices=sorted(train_idx),
        validation_indices=sorted(val_idx),
        test_indices=sorted(test_idx),
        purged_indices=sorted(purged),
        embargoed_indices=sorted(embargoed),
        train_start=train_start,
        train_end=train_end,
        validation_start=val_start,
        validation_end=val_end,
        test_start=test_start,
        test_end=test_end,
        counts={
            "train": len(train_idx),
            "validation": len(val_idx),
            "test": len(test_idx),
            "purged": len(purged),
            "embargoed": len(embargoed),
        },
        failed_constraint=failed,
        available_required=avail_req,
        config={
            "train_ratio": config.train_ratio,
            "validation_ratio": config.validation_ratio,
            "test_ratio": config.test_ratio,
            "purge": config.purge,
            "embargo_periods": config.embargo_periods,
            "min_samples_per_split": config.min_samples_per_split,
        },
    )


@dataclass(frozen=True)
class DataQualityReport:
    total_source_observations: int
    eligible_feature_rows: int
    valid_labels: int
    missing_labels: int
    invalid_observations: int
    coverage_gaps: list[str]
    duplicate_observations: int
    per_class_counts: dict[str, int]
    split_counts: dict[str, int]
    purged_samples: int
    embargoed_samples: int
    feature_availability_failures: int
    source_provenance: dict[str, Any]
    target_horizon_availability: dict[str, int]
    warnings: list[str]
    limitations: list[str]


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    dataset_schema_version: str
    forecasting_problem_id: str
    forecasting_problem_version: str
    instrument: str | None
    timeframe: str
    price_basis: str
    historical_interval_start: str | None
    historical_interval_end: str | None
    source_provenance: dict[str, Any]
    feature_set_version: str
    target_definition: str
    target_version: str
    split_config: dict[str, Any]
    purge_rule: str
    embargo_rule: str
    transformation_config: dict[str, Any]
    observation_count: int
    feature_row_count: int
    label_count: int
    valid_label_count: int
    exclusion_summary: dict[str, int]
    data_quality_summary: dict[str, Any]
    algorithm_version: str
    random_seed: int | None
    created_at: str
    reproducibility_limitations: list[str]


def build_quality_report(
    observations: Sequence[Observation],
    feature_rows: Sequence[dict[str, Any] | None],
    labels: Sequence[TargetLabel],
    split: SplitResult,
    source_provenance: dict[str, Any] | None = None,
    validation_summary: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
) -> DataQualityReport:
    eligible = sum(1 for r in feature_rows if r is not None)
    valid = sum(1 for lab in labels if lab.status == "valid")
    missing = sum(1 for lab in labels if lab.status != "valid")
    # duplicate timestamps
    seen: set[str] = set()
    dup = 0
    for o in observations:
        key = o.timestamp.isoformat()
        if key in seen:
            dup += 1
        seen.add(key)
    # per-class counts for direction
    class_counts: dict[str, int] = {}
    for lab in labels:
        if lab.status == "valid" and lab.target_type == "direction":
            name = {1.0: "up", -1.0: "down", 0.0: "neutral"}.get(
                lab.value if lab.value is not None else 0.0, str(lab.value)
            )
            class_counts[name] = class_counts.get(name, 0) + 1
    # target horizon availability
    horizon_avail = {
        "valid": valid,
        "missing_future_horizon": sum(
            1 for lab in labels if lab.status == "missing_future_horizon"
        ),
        "invalid_source": sum(1 for lab in labels if lab.status == "invalid_source_observation"),
        "insufficient": sum(1 for lab in labels if lab.status == "insufficient_observations"),
        "excluded": sum(1 for lab in labels if lab.status == "excluded"),
    }
    warnings: list[str] = []
    if valid < 30:
        warnings.append("valid label count is small; evaluation may be unstable")
    if eligible < 30:
        warnings.append("eligible feature row count is small")
    if split.status != "completed":
        warnings.append(f"split status is {split.status}")
    limitations = [
        "Historical labels use future observations for research only and must not be used as features.",
        "No predictive model has been trained or evaluated as a production model.",
    ]
    return DataQualityReport(
        total_source_observations=len(observations),
        eligible_feature_rows=eligible,
        valid_labels=valid,
        missing_labels=missing,
        invalid_observations=int((validation_summary or {}).get("rejected", 0) or 0),
        coverage_gaps=list((coverage or {}).get("missing_intervals", []) or []),
        duplicate_observations=dup,
        per_class_counts=class_counts,
        split_counts=dict(split.counts),
        purged_samples=len(split.purged_indices),
        embargoed_samples=len(split.embargoed_indices),
        feature_availability_failures=sum(1 for r in feature_rows if r is None),
        source_provenance=source_provenance or {},
        target_horizon_availability=horizon_avail,
        warnings=warnings,
        limitations=limitations,
    )


def build_manifest(
    dataset_id: str,
    spec: ForecastingProblemSpec,
    instrument: str | None,
    timeframe: str,
    observations: Sequence[Observation],
    feature_rows: Sequence[dict[str, Any] | None],
    labels: Sequence[TargetLabel],
    split: SplitResult,
    quality: DataQualityReport,
    split_config: SplitConfig,
    source_provenance: dict[str, Any] | None = None,
    seed: int | None = 42,
    lookback: int | None = None,
) -> DatasetManifest:
    from datetime import datetime as _dt

    valid_labels = sum(1 for lab in labels if lab.status == "valid")
    exclusion_summary = {
        "missing_future_horizon": sum(
            1 for lab in labels if lab.status == "missing_future_horizon"
        ),
        "invalid_source_observation": sum(
            1 for lab in labels if lab.status == "invalid_source_observation"
        ),
        "insufficient_observations": sum(
            1 for lab in labels if lab.status == "insufficient_observations"
        ),
        "excluded": sum(1 for lab in labels if lab.status == "excluded"),
    }
    return DatasetManifest(
        dataset_id=dataset_id,
        dataset_schema_version=DATASET_SCHEMA_VERSION,
        forecasting_problem_id=spec.problem_id,
        forecasting_problem_version=spec.version,
        instrument=instrument,
        timeframe=timeframe,
        price_basis=spec.price_basis,
        historical_interval_start=observations[0].timestamp.isoformat() if observations else None,
        historical_interval_end=observations[-1].timestamp.isoformat() if observations else None,
        source_provenance=source_provenance or {},
        feature_set_version=FEATURE_SET_VERSION,
        target_definition=spec.target_type,
        target_version=spec.version,
        split_config=split.config,
        purge_rule="exclude training samples whose outcome window overlaps validation/test interval",
        embargo_rule=f"embargo_periods={split_config.embargo_periods} observations (count-based, not a time duration)",
        transformation_config={
            "lookback": 20 if lookback is None else lookback,
            "point_in_time": True,
            "max_features": spec.max_features,
            "effective_feature_count": min(max(1, spec.max_features), len(FORECAST_FEATURE_NAMES)),
            "effective_feature_names": list(
                FORECAST_FEATURE_NAMES[
                    : min(max(1, spec.max_features), len(FORECAST_FEATURE_NAMES))
                ]
            ),
        },
        observation_count=len(observations),
        feature_row_count=sum(1 for r in feature_rows if r is not None),
        label_count=len(labels),
        valid_label_count=valid_labels,
        exclusion_summary=exclusion_summary,
        data_quality_summary=asdict(quality),
        algorithm_version=ALGORITHM_VERSION,
        random_seed=seed,
        created_at=_dt.now(UTC).isoformat(),
        reproducibility_limitations=[
            "Reproducibility depends on identical source observations and configuration.",
            "Upstream data availability and ordering must be preserved.",
        ],
    )


def mae(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    if not y_true:
        return float("nan")
    return sum(abs(a - b) for a, b in zip(y_true, y_pred, strict=True)) / len(y_true)


def rmse(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    if not y_true:
        return float("nan")
    return float(
        (sum((a - b) ** 2 for a, b in zip(y_true, y_pred, strict=True)) / len(y_true)) ** 0.5
    )


def mean_error(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    if not y_true:
        return float("nan")
    return sum(b - a for a, b in zip(y_true, y_pred, strict=True)) / len(y_true)


def r2_score(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    if not y_true:
        return float("nan")
    mean_y = sum(y_true) / len(y_true)
    ss_tot = sum((y - mean_y) ** 2 for y in y_true)
    if ss_tot == 0:
        return float("nan")
    ss_res = sum((a - b) ** 2 for a, b in zip(y_true, y_pred, strict=True))
    return 1.0 - ss_res / ss_tot


def accuracy(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    if not y_true:
        return float("nan")
    correct = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a == b)
    return correct / len(y_true)


def balanced_accuracy(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    classes = sorted(set(y_true))
    if not classes:
        return float("nan")
    recalls = []
    for c in classes:
        tp = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a == c and b == c)
        support = sum(1 for a in y_true if a == c)
        recalls.append(tp / support if support else 0.0)
    return sum(recalls) / len(recalls)


def confusion_matrix(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a, b in zip(y_true, y_pred, strict=True):
        key = f"{a}->{b}"
        out[key] = out.get(key, 0) + 1
    return out


def baseline_zero_return(y_true: Sequence[float]) -> dict[str, Any]:
    preds = [0.0 for _ in y_true]
    return {
        "name": "zero_return",
        "mae": mae(y_true, preds),
        "rmse": rmse(y_true, preds),
        "mean_error": mean_error(y_true, preds),
        "r2": r2_score(y_true, preds),
    }


def baseline_historical_mean(y_train: Sequence[float], y_test: Sequence[float]) -> dict[str, Any]:
    if not y_train:
        mean_val = 0.0
    else:
        mean_val = sum(y_train) / len(y_train)
    preds = [mean_val for _ in y_test]
    return {
        "name": "historical_mean",
        "fitted_value": mean_val,
        "mae": mae(y_test, preds),
        "rmse": rmse(y_test, preds),
        "mean_error": mean_error(y_test, preds),
        "r2": r2_score(y_test, preds),
    }


def baseline_majority_class(y_train: Sequence[float], y_test: Sequence[float]) -> dict[str, Any]:
    if not y_train:
        majority = 0.0
    else:
        counts: dict[float, int] = {}
        for v in y_train:
            counts[v] = counts.get(v, 0) + 1
        majority = max(counts.items(), key=lambda kv: kv[1])[0]
    preds = [majority for _ in y_test]
    return {
        "name": "majority_class",
        "majority_class": majority,
        "accuracy": accuracy(y_test, preds),
        "balanced_accuracy": balanced_accuracy(y_test, preds),
        "confusion_matrix": confusion_matrix(y_test, preds),
    }
