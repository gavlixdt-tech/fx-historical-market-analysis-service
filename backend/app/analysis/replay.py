"""Chronological, information-availability-aware historical replay."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from backend.app.analysis.forecasting import (
    ALGORITHM_VERSION,
    FEATURE_SET_VERSION,
    FORECAST_FEATURE_NAMES,
    ForecastingProblemSpec,
    build_point_in_time_features,
    generate_labels,
)
from backend.app.analysis.model_research import (
    HistogramGradientBoosting,
    Preprocessor,
    RandomForest,
    RidgeLogistic,
    RidgeRegression,
    classification_metrics,
    regression_metrics,
    supported_model_families,
    task_type_for_target,
)
from backend.app.analysis.observations import Observation, coerce_timestamp
from backend.app.schemas.replay import HistoricalReplayRequest

BOOTSTRAP_REPLICATES = 500
BOOTSTRAP_BLOCK_LENGTH = 5


def _regime_at(closes: list[float], index: int) -> str:
    """Classify a coarse regime using only closes available at this origin."""
    returns = [
        closes[position] / closes[position - 1] - 1.0
        for position in range(max(1, index - 59), index + 1)
        if closes[position - 1] > 0
    ]
    if len(returns) < 20:
        return "insufficient_history"
    recent = returns[-20:]
    mean = sum(recent) / len(recent)
    recent_std = math.sqrt(sum((value - mean) ** 2 for value in recent) / len(recent))
    long_mean = sum(returns) / len(returns)
    long_std = math.sqrt(sum((value - long_mean) ** 2 for value in returns) / len(returns))
    cumulative = closes[index] / closes[index - 20] - 1.0
    direction = 1.0 if cumulative >= 0 else -1.0
    consistency = sum(1 for value in recent if value * direction > 0) / len(recent)
    if long_std > 0 and recent_std > 1.5 * long_std:
        return "high_volatility"
    if cumulative >= 0.01 and consistency >= 0.6:
        return "trending_up"
    if cumulative <= -0.01 and consistency >= 0.6:
        return "trending_down"
    return "range_or_unclear"


def _fit_predict(
    family: str,
    task_type: str,
    train_features: list[list[float | None]],
    train_targets: list[float],
    current_features: list[float | None],
    *,
    seed: int,
) -> tuple[float, dict[str, float]]:
    preprocessor = Preprocessor().fit(train_features)
    train_x = preprocessor.transform(train_features)
    current_x = preprocessor.transform([current_features])
    if family in {"historical_mean", "volatility_mean"}:
        return sum(train_targets) / len(train_targets), {}
    if family == "zero_return":
        return 0.0, {}
    if family == "majority_class":
        counts: dict[float, int] = defaultdict(int)
        for target in train_targets:
            counts[target] += 1
        class_probabilities = {
            str(label): count / len(train_targets) for label, count in counts.items()
        }
        return (
            max(counts.items(), key=lambda item: (item[1], -item[0]))[0],
            class_probabilities,
        )
    model: RidgeLogistic | RandomForest | HistogramGradientBoosting
    if family == "ridge_regression":
        regression_model = RidgeRegression(alpha=1.0).fit(train_x, train_targets)
        return regression_model.predict(current_x)[0], {}
    elif family == "ridge_logistic":
        model = RidgeLogistic(alpha=1.0).fit(train_x, train_targets)
    elif family == "random_forest":
        model = RandomForest(task_type=task_type, n_estimators=20, max_depth=4, seed=seed)
        model.fit(train_x, train_targets)
    elif family == "histogram_gradient_boosting":
        model = HistogramGradientBoosting(
            task_type=task_type,
            n_estimators=30,
            learning_rate=0.1,
            max_depth=3,
            seed=seed,
        )
        model.fit(train_x, train_targets)
    else:
        raise ValueError(f"unsupported model family: {family}")
    prediction = model.predict(current_x)[0]
    probabilities: dict[str, float] = {}
    if task_type == "classification":
        for label, probability in zip(
            model.classes, model.predict_proba(current_x)[0], strict=True
        ):
            probabilities[str(label)] = probability
    return prediction, probabilities


def _bootstrap_improvement(
    improvements: list[float], *, seed: int, replicates: int = BOOTSTRAP_REPLICATES
) -> dict[str, Any]:
    count = len(improvements)
    if count < 20:
        return {
            "status": "insufficient_samples",
            "n": count,
            "block_length": BOOTSTRAP_BLOCK_LENGTH,
            "replicates": 0,
            "mean_improvement": sum(improvements) / count if count else None,
            "ci_95": None,
            "p_value_one_sided": None,
        }
    rng = random.Random(seed)  # noqa: S311
    observed = sum(improvements) / count
    centered = [value - observed for value in improvements]
    blocks = [
        centered[start : start + BOOTSTRAP_BLOCK_LENGTH]
        for start in range(count - BOOTSTRAP_BLOCK_LENGTH + 1)
    ]
    estimates: list[float] = []
    null_means: list[float] = []
    for _ in range(replicates):
        sample: list[float] = []
        null_sample: list[float] = []
        while len(sample) < count:
            block_index = rng.randrange(len(blocks))
            block = blocks[block_index]
            sample.extend(improvements[block_index : block_index + len(block)])
            null_sample.extend(block)
        estimates.append(sum(sample[:count]) / count)
        null_means.append(sum(null_sample[:count]) / count)
    estimates.sort()
    p_value = (1 + sum(value >= observed for value in null_means)) / (replicates + 1)
    return {
        "status": "computed",
        "n": count,
        "block_length": BOOTSTRAP_BLOCK_LENGTH,
        "replicates": replicates,
        "mean_improvement": observed,
        "ci_95": [
            estimates[int(0.025 * replicates)],
            estimates[min(replicates - 1, int(0.975 * replicates))],
        ],
        "p_value_one_sided": p_value,
    }


def _white_reality_check(
    improvements: dict[str, list[float]], *, seed: int, replicates: int = BOOTSTRAP_REPLICATES
) -> dict[str, Any]:
    names = list(improvements)
    if not names or len({len(improvements[name]) for name in names}) != 1:
        return {"status": "not_computed", "reason": "No common forecast-loss panel."}
    count = len(improvements[names[0]])
    if count < 20:
        return {"status": "insufficient_samples", "n": count, "replicates": 0}
    observed = max(sum(improvements[name]) / count for name in names)
    centered = {
        name: [value - sum(improvements[name]) / count for value in improvements[name]]
        for name in names
    }
    rng = random.Random(seed)  # noqa: S311
    starts = list(range(max(1, count - BOOTSTRAP_BLOCK_LENGTH + 1)))
    exceedances = 0
    for _ in range(replicates):
        sampled: dict[str, list[float]] = {name: [] for name in names}
        while len(sampled[names[0]]) < count:
            start = rng.choice(starts)
            for name in names:
                sampled[name].extend(centered[name][start : start + BOOTSTRAP_BLOCK_LENGTH])
        maximum = max(sum(sample[:count]) / count for sample in sampled.values())
        exceedances += maximum >= observed
    return {
        "status": "computed",
        "method": "White's Reality Check approximation with centered moving-block bootstrap",
        "n": count,
        "models_tested": names,
        "block_length": BOOTSTRAP_BLOCK_LENGTH,
        "replicates": replicates,
        "observed_max_mean_loss_improvement": observed,
        "p_value": (1 + exceedances) / (replicates + 1),
        "chronological_evaluation_remains_primary": True,
    }


def _probability_backtest_overfitting(
    losses: dict[str, list[float]],
) -> dict[str, Any]:
    names = list(losses)
    if len(names) < 2:
        return {"status": "not_computed", "reason": "At least two candidate models are required."}
    count = len(losses[names[0]])
    if count < 80 or any(len(losses[name]) != count for name in names):
        return {
            "status": "insufficient_samples",
            "n": count,
            "reason": "Requires at least 80 common out-of-sample predictions.",
        }
    segments = 8
    block_size = count // segments
    segment_indices = [
        list(range(position * block_size, (position + 1) * block_size))
        for position in range(segments)
    ]
    partitions = 0
    overfit = 0
    logits: list[float] = []
    for selected_segments in itertools.combinations(range(segments), segments // 2):
        selected_set = set(selected_segments)
        in_indices = [
            index
            for segment, indices in enumerate(segment_indices)
            if segment in selected_set
            for index in indices
        ]
        out_indices = [
            index
            for segment, indices in enumerate(segment_indices)
            if segment not in selected_set
            for index in indices
        ]
        in_scores = {
            name: sum(losses[name][index] for index in in_indices) / len(in_indices)
            for name in names
        }
        selected_model = min(names, key=lambda name: in_scores[name])
        out_scores = {
            name: sum(losses[name][index] for index in out_indices) / len(out_indices)
            for name in names
        }
        selected_score = out_scores[selected_model]
        rank = sum(value >= selected_score for value in out_scores.values()) / (len(names) + 1)
        clipped_rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(clipped_rank / (1 - clipped_rank)))
        overfit += rank < 0.5
        partitions += 1
    return {
        "status": "computed",
        "method": "supplementary combinatorial symmetric cross-validation over contiguous loss blocks",
        "n": count,
        "blocks": segments,
        "partitions": partitions,
        "probability_of_backtest_overfitting": overfit / partitions,
        "mean_rank_logit": sum(logits) / len(logits),
        "chronological_evaluation_remains_primary": True,
    }


def _calibration_report(
    targets: list[float],
    probabilities: list[dict[str, float]],
) -> dict[str, Any]:
    labels = sorted({str(value) for value in targets})
    if not labels or len(probabilities) != len(targets):
        return {"status": "not_available"}
    class_reports: dict[str, Any] = {}
    brier_total = 0.0
    ece_total = 0.0
    bin_count = 10
    for label in labels:
        observed = [float(str(target) == label) for target in targets]
        predicted = [min(max(row.get(label, 0.0), 0.0), 1.0) for row in probabilities]
        brier = sum(
            (actual - estimate) ** 2 for actual, estimate in zip(observed, predicted, strict=True)
        ) / len(targets)
        bins: list[dict[str, Any]] = []
        ece = 0.0
        for bucket in range(bin_count):
            lower = bucket / bin_count
            upper = (bucket + 1) / bin_count
            indices = [
                i
                for i, estimate in enumerate(predicted)
                if lower <= estimate < upper or (bucket == bin_count - 1 and estimate == 1.0)
            ]
            if not indices:
                bins.append(
                    {
                        "bin": bucket,
                        "count": 0,
                        "mean_probability": None,
                        "observed_frequency": None,
                    }
                )
                continue
            mean_probability = sum(predicted[i] for i in indices) / len(indices)
            observed_frequency = sum(observed[i] for i in indices) / len(indices)
            ece += len(indices) / len(targets) * abs(mean_probability - observed_frequency)
            bins.append(
                {
                    "bin": bucket,
                    "count": len(indices),
                    "mean_probability": mean_probability,
                    "observed_frequency": observed_frequency,
                }
            )
        class_reports[label] = {
            "brier_score": brier,
            "expected_calibration_error": ece,
            "bins": bins,
        }
        brier_total += brier
        ece_total += ece
    return {
        "status": "out_of_sample_descriptive_only",
        "class_brier_score_mean": brier_total / len(labels),
        "class_expected_calibration_error_mean": ece_total / len(labels),
        "classes": class_reports,
        "calibrated_probability_claim": False,
    }


def _metric_report(
    targets: list[float],
    predictions: list[float],
    task_type: str,
    probabilities: list[dict[str, float]],
) -> dict[str, Any]:
    if task_type == "regression":
        return regression_metrics(targets, predictions)
    classes = sorted({str(value) for value in [*targets, *predictions]})
    aligned_probabilities = [[row.get(label, 0.0) for label in classes] for row in probabilities]
    metrics = classification_metrics(targets, predictions, aligned_probabilities)
    calibration = _calibration_report(targets, probabilities)
    metrics["calibration"] = calibration
    return metrics


def run_historical_replay(request: HistoricalReplayRequest) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    timestamps = [coerce_timestamp(item.timestamp) for item in request.observations]
    available_at = [coerce_timestamp(item.available_at) for item in request.observations]
    observations = [
        Observation(
            timestamp=timestamps[index],
            open=item.open,
            high=item.high,
            low=item.low,
            close=item.close,
            volume=item.volume,
        )
        for index, item in enumerate(request.observations)
    ]
    spec = ForecastingProblemSpec(
        problem_id=request.problem.problem_id,
        version=request.problem.version,
        instrument_scope=tuple(request.problem.instrument_scope),
        input_timeframe=request.problem.input_timeframe,
        price_basis=request.problem.price_basis,
        feature_availability_policy=request.problem.feature_availability_policy,
        prediction_reference=request.problem.prediction_reference,
        prediction_horizon=request.problem.prediction_horizon,
        target_type=request.problem.target_type,
        target_units=request.problem.target_units,
        eligibility_rules=tuple(request.problem.eligibility_rules),
        label_generation_method=request.problem.label_generation_method,
        missing_observation_policy=request.problem.missing_observation_policy,
        required_historical_coverage=request.problem.required_historical_coverage,
        evaluation_protocol=request.problem.evaluation_protocol,
        known_limitations=tuple(request.problem.known_limitations),
        neutral_threshold=request.problem.neutral_threshold,
        volatility_window=request.problem.volatility_window,
        max_features=request.problem.max_features,
    )
    errors = spec.validate()
    if errors:
        raise ValueError("; ".join(errors))
    features = build_point_in_time_features(observations, spec, lookback=request.lookback)
    labels = generate_labels(observations, spec)

    # Optional cross-service context is a feature only after its own available_at
    # has passed the candle's information cutoff. Caller-supplied snapshots are
    # fingerprinted but remain unverified provenance, never signed evidence.
    session_names = (
        "Wellington", "Sydney", "Tokyo", "Hong Kong", "Singapore",
        "Frankfurt", "London", "New York",
    )
    open_window_names = ("sydney_open", "tokyo_open", "frankfurt_open", "london_open")
    kill_zone_names = (
        "ict_asia", "ict_london", "ict_new_york_am",
        "ict_london_close", "ict_new_york_pm",
    )
    context_feature_names = [
        *(f"session_{name.lower().replace(' ', '_')}" for name in session_names),
        *(f"open_window_{name}" for name in open_window_names),
        *(f"kill_zone_{name}" for name in kill_zone_names),
        "session_overlap_count",
        "liquidity_sweep_bullish", "liquidity_sweep_bearish",
        "liquidity_displacement_confirmed", "liquidity_midpoint_reached",
        "liquidity_midpoint_consolidation", "liquidity_invalidated",
    ]
    has_context = any(
        item.session_context is not None or item.liquidity_lifecycle is not None
        for item in request.observations
    )
    if has_context:
        for index, item in enumerate(request.observations):
            row = features[index]
            if row is None:
                continue
            session = item.session_context
            if session is not None and coerce_timestamp(session.available_at) <= available_at[index]:
                active_sessions = set(session.active_sessions)
                active_open_windows = set(session.active_open_windows)
                active_kill_zones = set(session.active_kill_zones)
                for name in session_names:
                    row[f"session_{name.lower().replace(' ', '_')}"] = float(name in active_sessions)
                for name in open_window_names:
                    row[f"open_window_{name}"] = float(name in active_open_windows)
                for name in kill_zone_names:
                    row[f"kill_zone_{name}"] = float(name in active_kill_zones)
                row["session_overlap_count"] = float(session.session_overlap_count)
            else:
                for name in context_feature_names[:18]:
                    row[name] = None
            lifecycle = item.liquidity_lifecycle
            if lifecycle is not None and coerce_timestamp(lifecycle.available_at) <= available_at[index]:
                state = lifecycle.state
                confirmed = state in {
                    "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT", "DISPLACEMENT_CONFIRMED",
                    "MIDPOINT_REACHED", "MIDPOINT_CONSOLIDATION_CANDIDATE",
                }
                row["liquidity_sweep_bullish"] = float(confirmed and lifecycle.direction == "bullish")
                row["liquidity_sweep_bearish"] = float(confirmed and lifecycle.direction == "bearish")
                row["liquidity_displacement_confirmed"] = float(
                    state in {"DISPLACEMENT_CONFIRMED", "MIDPOINT_REACHED", "MIDPOINT_CONSOLIDATION_CANDIDATE"}
                )
                row["liquidity_midpoint_reached"] = float(
                    state in {"MIDPOINT_REACHED", "MIDPOINT_CONSOLIDATION_CANDIDATE"}
                )
                row["liquidity_midpoint_consolidation"] = float(
                    state == "MIDPOINT_CONSOLIDATION_CANDIDATE"
                )
                row["liquidity_invalidated"] = float(state == "INVALIDATED")
            else:
                for name in context_feature_names[18:]:
                    row[name] = None
    task_type = task_type_for_target(spec.target_type)
    allowed = {item["name"] for item in supported_model_families(task_type)}
    baseline = (
        "majority_class"
        if task_type == "classification"
        else "volatility_mean"
        if spec.target_type == "realized_volatility"
        else "zero_return"
    )
    requested_families = list(request.model_families)
    if not requested_families:
        requested_families = [
            "ridge_logistic" if task_type == "classification" else "ridge_regression"
        ]
    invalid_families = sorted(set(requested_families) - allowed)
    if invalid_families:
        raise ValueError(f"unsupported model family for target: {', '.join(invalid_families)}")
    model_families = list(dict.fromkeys([baseline, *requested_families]))
    feature_names = list(FORECAST_FEATURE_NAMES[: min(spec.max_features, len(FORECAST_FEATURE_NAMES))])
    if has_context:
        remaining_feature_capacity = max(0, spec.max_features - len(feature_names))
        feature_names.extend(context_feature_names[:remaining_feature_capacity])
    closes = [observation.close for observation in observations]

    predictions: list[dict[str, Any]] = []
    records: dict[str, dict[str, list[Any]]] = {
        family: {
            "target": [],
            "prediction": [],
            "probabilities": [],
            "loss": [],
            "regime": [],
            "holdout": [],
        }
        for family in model_families
    }
    warnings: list[str] = []
    start_index = max(request.lookback - 1, spec.prediction_horizon + request.min_train_samples)
    holdout_cutoff = (
        coerce_timestamp(request.final_holdout_start)
        if request.final_holdout_start is not None
        else None
    )
    for index in range(start_index, len(observations)):
        current_label = labels[index]
        if (
            features[index] is None
            or current_label.status != "valid"
            or current_label.value is None
        ):
            continue
        future_index = current_label.future_index
        if future_index is None:
            continue
        decision_time = available_at[index]
        holdout = holdout_cutoff is not None and timestamps[index] >= holdout_cutoff
        training_cutoff = holdout_cutoff if holdout else decision_time
        if training_cutoff is None:
            raise RuntimeError("holdout replay is missing its training cutoff")
        if available_at[future_index] <= decision_time:
            continue
        eligible_train: list[int] = []
        for train_index in range(index):
            train_label = labels[train_index]
            train_future_index = train_label.future_index
            if (
                features[train_index] is None
                or train_label.status != "valid"
                or train_label.value is None
                or train_future_index is None
            ):
                continue
            if train_future_index >= index or available_at[train_future_index] > training_cutoff:
                continue
            if holdout:
                if holdout_cutoff is None:
                    raise RuntimeError("holdout replay is missing its cutoff")
                if (
                    timestamps[train_index] >= holdout_cutoff
                    or timestamps[train_future_index] >= holdout_cutoff
                    or available_at[train_future_index] > holdout_cutoff
                ):
                    continue
            eligible_train.append(train_index)
        if request.embargo_periods:
            eligible_train = eligible_train[: max(0, len(eligible_train) - request.embargo_periods)]
        if request.validation_mode == "rolling" and request.rolling_window is not None:
            eligible_train = eligible_train[-request.rolling_window :]
        if len(eligible_train) < request.min_train_samples:
            continue
        training_target_end_index = labels[eligible_train[-1]].future_index
        if training_target_end_index is None:
            raise RuntimeError("eligible training sample is missing its target index")
        train_features = [
            [features[train_index].get(name) for name in feature_names]  # type: ignore[union-attr]
            for train_index in eligible_train
        ]
        train_targets: list[float] = []
        for train_index in eligible_train:
            target_value = labels[train_index].value
            if target_value is None:
                raise RuntimeError("eligible training sample is missing its target value")
            train_targets.append(float(target_value))
        training_outcomes_available_by_cutoff = True
        for train_index in eligible_train:
            target_index = labels[train_index].future_index
            if target_index is None:
                raise RuntimeError("eligible training sample is missing its target index")
            if available_at[target_index] > training_cutoff:
                training_outcomes_available_by_cutoff = False
                break
        current_features = [features[index].get(name) for name in feature_names]  # type: ignore[union-attr]
        regime = _regime_at(closes, index)
        actual = float(current_label.value)
        forecast_row: dict[str, Any] = {
            "reference_timestamp": timestamps[index].isoformat(),
            "information_cutoff": decision_time.isoformat(),
            "training_information_cutoff": training_cutoff.isoformat(),
            "target_timestamp": timestamps[future_index].isoformat(),
            "target_available_at": available_at[future_index].isoformat(),
            "training_samples": len(eligible_train),
            "training_reference_end": timestamps[eligible_train[-1]].isoformat(),
            "training_target_end": timestamps[training_target_end_index].isoformat(),
            "training_outcomes_available_by_cutoff": training_outcomes_available_by_cutoff,
            "regime": regime,
            "actual": actual,
            "forecasts": {},
        }
        session_context = request.observations[index].session_context
        lifecycle_context = request.observations[index].liquidity_lifecycle
        session_known = (
            session_context is not None
            and coerce_timestamp(session_context.available_at) <= decision_time
        )
        lifecycle_known = (
            lifecycle_context is not None
            and coerce_timestamp(lifecycle_context.available_at) <= decision_time
        )
        forecast_row["market_context"] = {
            "session": {
                "status": "available" if session_known else (
                    "not_yet_available" if session_context is not None else "not_supplied"
                ),
                "source_reference": session_context.source_reference if session_known else None,
                "active_sessions": session_context.active_sessions if session_known else [],
                "active_open_windows": session_context.active_open_windows if session_known else [],
                "active_kill_zones": session_context.active_kill_zones if session_known else [],
                "session_overlap_count": session_context.session_overlap_count if session_known else None,
            },
            "liquidity_lifecycle": {
                "status": "available" if lifecycle_known else (
                    "not_yet_available" if lifecycle_context is not None else "not_supplied"
                ),
                "source_event_id": lifecycle_context.source_event_id if lifecycle_known else None,
                "state": lifecycle_context.state if lifecycle_known else None,
                "direction": lifecycle_context.direction if lifecycle_known else None,
            },
            "provenance_status": "caller_asserted_unverified",
        }
        for model_index, family in enumerate(model_families):
            predicted, probabilities = _fit_predict(
                family,
                task_type,
                train_features,
                train_targets,
                current_features,
                seed=request.random_seed + index + model_index,
            )
            forecast_row["forecasts"][family] = {
                "prediction": predicted,
                "class_probabilities": probabilities,
            }
            loss = (
                abs(actual - predicted) if task_type == "regression" else float(actual != predicted)
            )
            records[family]["target"].append(actual)
            records[family]["prediction"].append(predicted)
            records[family]["probabilities"].append(probabilities)
            records[family]["loss"].append(loss)
            records[family]["regime"].append(regime)
            records[family]["holdout"].append(holdout)
        predictions.append(forecast_row)

    if not predictions:
        raise ValueError(
            "Insufficient point-in-time training history for a valid replay prediction."
        )
    model_reports: list[dict[str, Any]] = []
    improvements_by_model: dict[str, list[float]] = {}
    losses_by_candidate: dict[str, list[float]] = {}
    baseline_losses = records[baseline]["loss"]
    selection_positions = [
        position
        for position, is_holdout in enumerate(records[baseline]["holdout"])
        if not is_holdout
    ]
    for model_index, family in enumerate(model_families):
        target_values = records[family]["target"]
        predicted_values = records[family]["prediction"]
        probability_values = records[family]["probabilities"]
        all_metrics = _metric_report(target_values, predicted_values, task_type, probability_values)
        regimes: dict[str, list[int]] = defaultdict(list)
        for position, regime in enumerate(records[family]["regime"]):
            regimes[regime].append(position)
        regime_metrics = {
            regime: _metric_report(
                [target_values[position] for position in positions],
                [predicted_values[position] for position in positions],
                task_type,
                [probability_values[position] for position in positions],
            )
            for regime, positions in sorted(regimes.items())
        }
        holdout_positions = [
            position for position, is_holdout in enumerate(records[family]["holdout"]) if is_holdout
        ]
        holdout_metrics = (
            _metric_report(
                [target_values[position] for position in holdout_positions],
                [predicted_values[position] for position in holdout_positions],
                task_type,
                [probability_values[position] for position in holdout_positions],
            )
            if holdout_positions
            else None
        )
        selection_metrics = (
            _metric_report(
                [target_values[position] for position in selection_positions],
                [predicted_values[position] for position in selection_positions],
                task_type,
                [probability_values[position] for position in selection_positions],
            )
            if selection_positions
            else None
        )
        report: dict[str, Any] = {
            "model_family": family,
            "n_predictions": len(target_values),
            "primary_metric": "mae" if task_type == "regression" else "accuracy",
            "out_of_sample_metrics": all_metrics,
            "model_selection_metrics": selection_metrics,
            "regime_metrics": regime_metrics,
            "declared_holdout": {
                "status": "reported_integrity_unverified" if holdout_positions else "not_declared",
                "start": request.final_holdout_start.isoformat()
                if request.final_holdout_start
                else None,
                "n_predictions": len(holdout_positions),
                "metrics": holdout_metrics,
            },
        }
        if family != baseline:
            improvements = [
                baseline_losses[position] - records[family]["loss"][position]
                for position in selection_positions
            ]
            improvements_by_model[family] = improvements
            losses_by_candidate[family] = [
                records[family]["loss"][position] for position in selection_positions
            ]
            report["vs_baseline"] = _bootstrap_improvement(
                improvements,
                seed=request.random_seed + model_index,
            )
        else:
            report["vs_baseline"] = {"status": "baseline"}
        model_reports.append(report)

    reality_check = _white_reality_check(improvements_by_model, seed=request.random_seed)
    pbo = _probability_backtest_overfitting(losses_by_candidate)
    if len(predictions) < 100:
        warnings.append("Small out-of-sample sample limits statistical reliability.")
    if request.synthetic:
        warnings.append("Synthetic input is for software validation only, not predictive evidence.")
    if has_context:
        warnings.append(
            "Session and liquidity lifecycle context is caller-supplied and not independently authenticated; "
            "each context field is excluded until its available_at is within that prediction's information cutoff."
        )
    if request.final_holdout_start is None:
        warnings.append("No final holdout start was declared.")
    elif sum(records[baseline]["holdout"]) < 20:
        warnings.append("Declared final holdout contains fewer than 20 predictions.")
    if request.embargo_periods:
        warnings.append(
            "Embargo excludes the most recent eligible training samples at every origin."
        )
    if not selection_positions:
        warnings.append("No pre-holdout model-selection predictions were generated.")

    observation_payload = [
        {
            "source_record_id": item.source_record_id,
            "timestamp": timestamps[index].isoformat(),
            "available_at": available_at[index].isoformat(),
            "open": item.open,
            "high": item.high,
            "low": item.low,
            "close": item.close,
            "volume": item.volume,
            "session_context": item.session_context.model_dump(mode="json") if item.session_context else None,
            "liquidity_lifecycle": item.liquidity_lifecycle.model_dump(mode="json") if item.liquidity_lifecycle else None,
        }
        for index, item in enumerate(request.observations)
    ]
    fingerprint_payload = {
        "instrument": request.instrument,
        "timeframe": request.timeframe,
        "source_dataset_id": request.source_dataset_id,
        "problem": request.problem.model_dump(mode="json"),
        "observations": observation_payload,
    }
    dataset_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return {
        "replay_id": str(uuid.uuid4()),
        "status": "completed_with_warnings" if warnings else "completed",
        "instrument": request.instrument,
        "timeframe": request.timeframe,
        "target_type": spec.target_type,
        "dataset_fingerprint": dataset_fingerprint,
        "source_dataset_id": request.source_dataset_id,
        "provenance_status": "synthetic_fixture"
        if request.synthetic
        else "caller_asserted_unverified",
        "synthetic": request.synthetic,
        "n_observations": len(observations),
        "n_predictions": len(predictions),
        "validation_mode": request.validation_mode,
        "predictions": predictions,
        "models": model_reports,
        "robustness": {
            "primary_protocol": "chronological_rolling_origin_replay",
            "purging": "training outcomes must be fully available before each prediction cutoff",
            "embargo_periods": request.embargo_periods,
            "selection_diagnostics_use": "pre-holdout predictions only",
            "n_model_selection_predictions": len(selection_positions),
            "white_reality_check": reality_check,
            "probability_of_backtest_overfitting": pbo,
            "regime_method": "causal 20-observation return and volatility heuristic",
            "regime_metrics_are_calibrated": False,
            "service_ablation": {
                "status": "not_available",
                "reason": "Historical point-in-time outputs from other services are not part of this request contract.",
            },
            "future_evaluation": {
                "status": "not_established",
                "reason": "A retrospective replay cannot establish performance on future data.",
            },
        },
        "reproducibility": {
            "algorithm_version": ALGORITHM_VERSION,
            "feature_set_version": FEATURE_SET_VERSION,
            "dataset_fingerprint": dataset_fingerprint,
            "random_seed": request.random_seed,
            "validation_mode": request.validation_mode,
            "lookback": request.lookback,
            "min_train_samples": request.min_train_samples,
            "rolling_window": request.rolling_window,
            "embargo_periods": request.embargo_periods,
            "model_families": model_families,
            "model_hyperparameters": {
                "ridge_alpha": 1.0,
                "random_forest": {"n_estimators": 20, "max_depth": 4},
                "histogram_gradient_boosting": {
                    "n_estimators": 30,
                    "learning_rate": 0.1,
                    "max_depth": 3,
                },
            },
            "final_holdout_start": request.final_holdout_start.isoformat()
            if request.final_holdout_start
            else None,
            "bootstrap": {
                "replicates": BOOTSTRAP_REPLICATES,
                "block_length": BOOTSTRAP_BLOCK_LENGTH,
                "selection_diagnostics_exclude_declared_holdout": True,
            },
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "artifact_persistence": "not_persisted",
        },
        "warnings": warnings,
        "limitations": [
            "This is a reconstructed model-class replay, not an archived prediction originally emitted at each historical time.",
            "available_at and source_dataset_id are caller supplied and are not independently verified.",
            "Source-data revisions, corrections, and historical service/model artifacts are not represented by this contract.",
            "The declared holdout is reported in the same response and its non-selection cannot be independently verified.",
            "Regime labels are descriptive heuristics and are not external market-regime service outputs.",
            "White's Reality Check and PBO are supplementary diagnostics; chronological replay is primary.",
            "No trade simulation, execution, costs, or profitability is measured.",
            "Experiments and model artifacts are not persisted by this endpoint.",
        ],
    }
