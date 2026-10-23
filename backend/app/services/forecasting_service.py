"""Forecasting-readiness orchestration (no model training)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any, cast

from backend.app.analysis.observations import coerce_timestamp
from backend.app.services.analysis_service import AnalysisService


class ForecastingService(AnalysisService):
    def __init__(self, settings: Any, upstream_client: Any) -> None:
        super().__init__(settings, upstream_client)
        self._experiments: dict[str, dict[str, Any]] = {}

    async def list_forecasting_targets(self) -> list[dict[str, Any]]:
        from backend.app.analysis.forecasting import FEATURE_SPECS

        return [
            {
                "name": "future_return",
                "formula": "P_{t+h}/P_t - 1",
                "units": "fraction",
                "description": "Future-horizon simple return using an exact future observation.",
            },
            {
                "name": "log_return",
                "formula": "ln(P_{t+h}/P_t)",
                "units": "log units",
                "description": "Logarithmic future return for positive prices.",
            },
            {
                "name": "direction",
                "formula": "sign(R_{t,h}) with neutral threshold",
                "units": "class",
                "description": "Directional target: up, down, or neutral.",
            },
            {
                "name": "realized_volatility",
                "formula": "sample std of returns after t",
                "units": "return units",
                "description": "Future realized volatility using returns strictly after the reference timestamp.",
            },
            {
                "name": "feature_specs",
                "formula": "point-in-time feature catalogue",
                "units": "metadata",
                "description": f"{len(FEATURE_SPECS)} point-in-time features available.",
            },
        ]

    async def validate_forecasting_problem(
        self, spec_input: Any
    ) -> tuple[bool, list[str], dict[str, Any]]:
        from backend.app.analysis.forecasting import ForecastingProblemSpec

        spec = ForecastingProblemSpec(
            problem_id=spec_input.problem_id,
            version=spec_input.version,
            instrument_scope=tuple(spec_input.instrument_scope),
            input_timeframe=spec_input.input_timeframe,
            price_basis=spec_input.price_basis,
            feature_availability_policy=spec_input.feature_availability_policy,
            prediction_reference=spec_input.prediction_reference,
            prediction_horizon=spec_input.prediction_horizon,
            target_type=spec_input.target_type,
            target_units=spec_input.target_units,
            eligibility_rules=tuple(spec_input.eligibility_rules),
            label_generation_method=spec_input.label_generation_method,
            missing_observation_policy=spec_input.missing_observation_policy,
            required_historical_coverage=spec_input.required_historical_coverage,
            evaluation_protocol=spec_input.evaluation_protocol,
            known_limitations=tuple(spec_input.known_limitations),
            neutral_threshold=spec_input.neutral_threshold,
            volatility_window=spec_input.volatility_window,
            max_features=spec_input.max_features,
        )
        errors = spec.validate()
        return len(errors) == 0, errors, dataclasses.asdict(spec)

    async def construct_features(self, request: Any, request_id: str):
        from backend.app.analysis.forecasting import (
            FEATURE_SPECS,
            ForecastingProblemSpec,
            build_point_in_time_features,
        )

        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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
        rows = build_point_in_time_features(
            observations,
            spec,
            lookback=request.lookback,
            point_in_time_regime_labels=request.point_in_time_regime_labels,
            regime_point_in_time_verified=request.regime_point_in_time_verified,
        )
        feature_specs = [dataclasses.asdict(s) for s in FEATURE_SPECS]
        excluded = sum(1 for r in rows if r is None)
        valid_rows = [r for r in rows if r is not None]
        return valid_rows, feature_specs, excluded, instrument, timeframe

    async def generate_forecasting_labels(self, request: Any, request_id: str):
        from backend.app.analysis.forecasting import ForecastingProblemSpec, generate_labels

        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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
        labels = generate_labels(observations, spec)
        return (
            [dataclasses.asdict(lab) for lab in labels],
            sum(1 for lab in labels if lab.status == "valid"),
            len(labels),
            instrument,
            timeframe,
        )

    async def build_forecasting_dataset(self, request: Any, request_id: str):
        from backend.app.analysis.forecasting import (
            ForecastingProblemSpec,
            SplitConfig,
            build_manifest,
            build_point_in_time_features,
            build_quality_report,
            chronological_split,
            generate_labels,
        )

        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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
        rows = build_point_in_time_features(observations, spec, lookback=request.lookback)
        labels = generate_labels(observations, spec)
        ref_ts = [o.timestamp for o in observations]
        outcome_ends = []
        for lab in labels:
            if lab.future_timestamp is None:
                outcome_ends.append(observations[-1].timestamp)
            else:
                outcome_ends.append(coerce_timestamp(lab.future_timestamp))
        sc = request.split
        split_config = SplitConfig(
            train_ratio=sc.train_ratio,
            validation_ratio=sc.validation_ratio,
            test_ratio=sc.test_ratio,
            train_end=sc.train_end,
            validation_end=sc.validation_end,
            purge=sc.purge,
            embargo_periods=sc.embargo_periods,
            min_samples_per_split=sc.min_samples_per_split,
        )
        split = chronological_split(ref_ts, split_config, outcome_ends)
        dataset_id = str(uuid.uuid4())
        prov = {"instrument": instrument, "timeframe": timeframe}
        quality = build_quality_report(observations, rows, labels, split, prov)
        manifest = build_manifest(
            dataset_id,
            spec,
            instrument,
            timeframe or spec.input_timeframe,
            observations,
            rows,
            labels,
            split,
            quality,
            split_config,
            prov,
            42,
        )
        baselines = None
        if request.include_baselines:
            from backend.app.analysis.forecasting import (
                baseline_historical_mean,
                baseline_majority_class,
                baseline_zero_return,
            )

            train_targets = [
                labels[i].value
                for i in split.train_indices
                if labels[i].status == "valid" and labels[i].value is not None
            ]
            test_targets = [
                labels[i].value
                for i in split.test_indices
                if labels[i].status == "valid" and labels[i].value is not None
            ]
            baselines = {
                "zero_return": baseline_zero_return(cast(list[float], test_targets)),
                "historical_mean": baseline_historical_mean(
                    cast(list[float], train_targets), cast(list[float], test_targets)
                ),
            }
            if spec.target_type == "direction":
                baselines["majority_class"] = baseline_majority_class(
                    cast(list[float], train_targets), cast(list[float], test_targets)
                )
        manifest_dict = dataclasses.asdict(manifest)
        quality_dict = dataclasses.asdict(quality)
        split_dict = {
            "status": split.status,
            "train_indices": split.train_indices,
            "validation_indices": split.validation_indices,
            "test_indices": split.test_indices,
            "purged_indices": split.purged_indices,
            "embargoed_indices": split.embargoed_indices,
            "counts": split.counts,
            "boundaries": {
                "train_start": split.train_start,
                "train_end": split.train_end,
                "validation_start": split.validation_start,
                "validation_end": split.validation_end,
                "test_start": split.test_start,
                "test_end": split.test_end,
            },
            "failed_constraint": split.failed_constraint,
            "available_required": split.available_required,
        }
        return {
            "status": "completed" if split.status == "completed" else split.status,
            "manifest": manifest_dict,
            "quality": quality_dict,
            "split": split_dict,
            "feature_count": sum(1 for r in rows if r is not None),
            "label_count": len(labels),
            "valid_label_count": sum(1 for lab in labels if lab.status == "valid"),
            "baselines": baselines,
            "warnings": quality.warnings,
            "limitations": quality.limitations,
        }

    async def compute_forecasting_baselines(self, request: Any, request_id: str):
        from backend.app.analysis.forecasting import (
            baseline_historical_mean,
            baseline_majority_class,
            baseline_zero_return,
        )

        train = request.train_targets
        test = request.test_targets
        metrics: dict[str, Any] = {
            "zero_return": baseline_zero_return(test),
            "historical_mean": baseline_historical_mean(train, test),
        }
        if request.task_type == "classification":
            metrics["majority_class"] = baseline_majority_class(train, test)
        return metrics

    async def list_model_families(self, task_type: str | None = None) -> list[dict[str, Any]]:
        from backend.app.analysis.model_research import supported_model_families

        return supported_model_families(task_type)

    async def validate_experiment(self, request: Any) -> tuple[bool, list[str], dict[str, Any]]:
        from backend.app.analysis.forecasting import ForecastingProblemSpec
        from backend.app.analysis.model_research import task_type_for_target

        errors: list[str] = []
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
        errors.extend(spec.validate())
        tt = task_type_for_target(spec.target_type)
        allowed = {f["name"] for f in await self.list_model_families(tt)}
        if not request.model_families:
            # default to all supported families for the target type
            request_model_families = [f["name"] for f in await self.list_model_families(tt)]
        else:
            request_model_families = list(request.model_families)
        for mf in request_model_families:
            if mf not in allowed:
                errors.append(f"unsupported model family for target: {mf}")
        if request.n_folds < 1 or request.n_folds > 5:
            errors.append("n_folds must be between 1 and 5")
        if request.min_train_samples < 10:
            errors.append("min_train_samples must be >= 10")
        # resource limits
        if request.limit is not None and request.limit > 2000:
            errors.append("limit exceeds experiment resource cap (2000)")
        config = {
            "problem": dataclasses.asdict(spec),
            "lookback": request.lookback,
            "n_folds": request.n_folds,
            "min_train_samples": request.min_train_samples,
            "purge": request.purge,
            "embargo_periods": request.embargo_periods,
            "model_families": request_model_families,
            "random_seed": request.random_seed,
            "calibration": request.calibration,
            "task_type": tt,
        }
        return len(errors) == 0, errors, config

    async def run_experiment(self, request: Any, request_id: str) -> dict[str, Any]:
        import hashlib
        import json
        from datetime import UTC, datetime

        from backend.app.analysis.forecasting import (
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
            fold_bootstrap_ci,
            regression_metrics,
            task_type_for_target,
            walk_forward_folds,
        )

        started_at = datetime.now(UTC).isoformat()
        valid, errors, config = await self.validate_experiment(request)
        from backend.app.core.errors import ValidationError as AppValidationError

        if not valid:
            raise AppValidationError("; ".join(errors))

        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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

        rows = build_point_in_time_features(observations, spec, lookback=request.lookback)
        labels = generate_labels(observations, spec)

        feature_names = [
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
        ]

        X_rows: list[dict[str, Any]] = []
        y_vals: list[float] = []
        ts_list: list[Any] = []
        outcome_ends: list[Any] = []
        for i, obs in enumerate(observations):
            row = rows[i]
            lab = labels[i]
            if row is None or lab.status != "valid" or lab.value is None:
                continue
            X_rows.append(row)
            y_vals.append(float(lab.value))
            ts_list.append(obs.timestamp)
            if lab.future_timestamp is None:
                outcome_ends.append(observations[-1].timestamp)
            else:
                outcome_ends.append(coerce_timestamp(lab.future_timestamp))

        if len(y_vals) < request.min_train_samples * 2:
            # insufficient data
            pass

        # dataset fingerprint
        fp_payload = {
            "instrument": instrument,
            "timeframe": timeframe,
            "problem": request.problem.problem_id,
            "version": request.problem.version,
            "lookback": request.lookback,
            "n": len(y_vals),
            "timestamps": [t.isoformat() for t in ts_list],
        }
        dataset_fingerprint = hashlib.sha256(
            json.dumps(fp_payload, sort_keys=True).encode()
        ).hexdigest()

        tt = task_type_for_target(spec.target_type)

        # model families
        if not request.model_families:
            model_families = [f["name"] for f in await self.list_model_families(tt)]
        else:
            model_families = list(request.model_families)

        # walk-forward folds
        folds = walk_forward_folds(
            len(y_vals),
            n_folds=request.n_folds,
            min_train=request.min_train_samples,
            purge=request.purge,
            embargo_periods=request.embargo_periods,
            outcome_ends=outcome_ends,
            timestamps=ts_list,
        )

        warnings: list[str] = []
        limitations: list[str] = list(spec.known_limitations)
        if not folds:
            warnings.append("insufficient data for walk-forward evaluation")
        if len(y_vals) < 100:
            warnings.append("small sample size limits reliability")

        # per-model results
        model_results: list[dict[str, Any]] = []
        pass

        # baseline name per task
        baseline_name = "zero_return" if tt == "regression" else "majority_class"
        if spec.target_type == "realized_volatility":
            baseline_name = "volatility_mean"
        for mf in model_families:
            fold_metrics_list: list[dict[str, Any]] = []
            fold_primary: list[float] = []
            selected_configs: list[dict[str, Any]] = []
            for fold in folds:
                tr = fold["train_indices"]
                va = fold["validation_indices"]
                te = fold["test_indices"]
                if not tr or not va or not te:
                    continue
                X_train = [[X_rows[i].get(fn) for fn in feature_names] for i in tr]
                y_train = [y_vals[i] for i in tr]
                X_val = [[X_rows[i].get(fn) for fn in feature_names] for i in va]
                y_val = [y_vals[i] for i in va]
                X_test = [[X_rows[i].get(fn) for fn in feature_names] for i in te]
                y_test = [y_vals[i] for i in te]

                pre = Preprocessor()
                pre.fit(X_train)
                Xtr_p = pre.transform(X_train)
                Xva_p = pre.transform(X_val)
                Xte_p = pre.transform(X_test)

                proba_test = None
                if mf == "zero_return":
                    preds_test = [0.0 for _ in y_test]
                    selected = {"model": mf}
                elif mf in ("historical_mean", "volatility_mean"):
                    mv = sum(y_train) / len(y_train) if y_train else 0.0
                    preds_test = [mv for _ in y_test]
                    selected = {"model": mf, "fitted_value": mv}
                elif mf == "majority_class":
                    counts: dict[float, int] = {}
                    for v in y_train:
                        counts[v] = counts.get(v, 0) + 1
                    maj = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0] if counts else 0.0
                    preds_test = [maj for _ in y_test]
                    selected = {"model": mf, "majority_class": maj}
                else:
                    best_cfg: dict[str, Any] = {}
                    best_score = None
                    m: Any = None
                    if mf == "ridge_regression":
                        for alpha in (0.1, 1.0, 10.0):
                            m = RidgeRegression(alpha=alpha)
                            m.fit(Xtr_p, y_train)
                            vp = m.predict(Xva_p)
                            from backend.app.analysis.forecasting import mae as _mae

                            vm_mae = _mae(y_val, vp)
                            if best_score is None or vm_mae < best_score:
                                best_score = vm_mae
                                best_cfg = {"alpha": alpha}
                    elif mf == "ridge_logistic":
                        for alpha in (0.1, 1.0, 10.0):
                            m = RidgeLogistic(alpha=alpha)
                            m.fit(Xtr_p, y_train)
                            vp = m.predict(Xva_p)
                            vm = classification_metrics(y_val, vp)
                            score = -vm["accuracy"]
                            if best_score is None or score < best_score:
                                best_score = score
                                best_cfg = {"alpha": alpha}
                    model: Any = None
                    if mf == "ridge_regression":
                        model = RidgeRegression(alpha=best_cfg.get("alpha", 1.0))
                    elif mf == "ridge_logistic":
                        model = RidgeLogistic(alpha=best_cfg.get("alpha", 1.0))
                    elif mf == "random_forest":
                        model = RandomForest(
                            task_type=tt,
                            n_estimators=20,
                            max_depth=4,
                            seed=request.random_seed + fold["fold"],
                        )
                    elif mf == "histogram_gradient_boosting":
                        model = HistogramGradientBoosting(
                            task_type=tt,
                            n_estimators=30,
                            learning_rate=0.1,
                            max_depth=3,
                            seed=request.random_seed + fold["fold"],
                        )
                    else:
                        model = None
                    if model is not None:
                        model.fit(Xtr_p, y_train)
                        preds_test = model.predict(Xte_p)
                        selected = {"model": mf, "hyperparameters": best_cfg}
                        if tt == "classification" and hasattr(model, "predict_proba"):
                            proba_test = model.predict_proba(Xte_p)
                    else:
                        preds_test = (
                            [0.0 for _ in y_test]
                            if tt == "regression"
                            else [y_train[0] if y_train else 0.0 for _ in y_test]
                        )
                        selected = {"model": mf, "error": "unsupported"}

                selected_configs.append({"fold": fold["fold"], "config": selected})

                if tt == "regression":
                    mmetrics = regression_metrics(y_test, preds_test)
                    primary = mmetrics["mae"]
                else:
                    mmetrics = classification_metrics(y_test, preds_test, proba_test)
                    primary = mmetrics["accuracy"]

                fold_row = {
                    "fold": fold["fold"],
                    "train_count": len(tr),
                    "validation_count": len(va),
                    "test_count": len(te),
                    "purged_count": len(fold["purged_indices"]),
                    "embargoed_count": len(fold["embargoed_indices"]),
                    "test_range": [
                        ts_list[te[0]].isoformat() if te else None,
                        ts_list[te[-1]].isoformat() if te else None,
                    ],
                    "metrics": mmetrics,
                    "selected_config": selected,
                }
                fold_metrics_list.append(fold_row)
                try:
                    fold_primary.append(float(primary))
                except (TypeError, ValueError):
                    fold_primary.append(float("nan"))
            if fold_primary:
                agg_primary = sum(fold_primary) / len(fold_primary)
                ci = fold_bootstrap_ci(fold_primary, seed=request.random_seed)
            else:
                agg_primary = float("nan")
                ci = {"mean": None, "ci_lower": None, "ci_upper": None, "n_boot": 0}

            baseline_primary_vals: list[float] = []
            for fold in folds:
                te = fold["test_indices"]
                tr = fold["train_indices"]
                if not tr or not te:
                    continue
                y_train = [y_vals[i] for i in tr]
                y_test = [y_vals[i] for i in te]
                if tt == "regression":
                    if baseline_name == "volatility_mean":
                        bv = sum(y_train) / len(y_train) if y_train else 0.0
                    elif baseline_name == "zero_return":
                        bv = 0.0
                    else:
                        bv = sum(y_train) / len(y_train) if y_train else 0.0
                    bpreds = [bv for _ in y_test]
                    baseline_primary_vals.append(regression_metrics(y_test, bpreds)["mae"])
                else:
                    counts2: dict[float, int] = {}
                    for v in y_train:
                        counts2[v] = counts2.get(v, 0) + 1
                    maj2 = (
                        max(counts2.items(), key=lambda kv: (kv[1], -kv[0]))[0] if counts2 else 0.0
                    )
                    bpreds = [maj2 for _ in y_test]
                    baseline_primary_vals.append(classification_metrics(y_test, bpreds)["accuracy"])
            baseline_agg = (
                sum(baseline_primary_vals) / len(baseline_primary_vals)
                if baseline_primary_vals
                else float("nan")
            )
            improvement = (
                (baseline_agg - agg_primary) if tt == "regression" else (agg_primary - baseline_agg)
            )

            model_results.append(
                {
                    "model_family": mf,
                    "task_type": tt,
                    "n_folds": len(fold_metrics_list),
                    "folds": fold_metrics_list,
                    "aggregate_primary_metric": agg_primary,
                    "primary_metric_ci": ci,
                    "baseline_name": baseline_name,
                    "baseline_aggregate_primary": baseline_agg,
                    "improvement_vs_baseline": improvement,
                    "selected_configs": selected_configs,
                }
            )
        # folds summary for response
        fold_summary = []
        for fold in folds:
            fold_summary.append(
                {
                    "fold": fold["fold"],
                    "train_count": len(fold["train_indices"]),
                    "validation_count": len(fold["validation_indices"]),
                    "test_count": len(fold["test_indices"]),
                    "purged_count": len(fold["purged_indices"]),
                    "embargoed_count": len(fold["embargoed_indices"]),
                }
            )

        completed_at = datetime.now(UTC).isoformat()
        experiment_id = str(uuid.uuid4())

        artifact_payload = {
            "experiment_id": experiment_id,
            "dataset_fingerprint": dataset_fingerprint,
            "model_results": model_results,
        }
        artifact_json = json.dumps(artifact_payload, sort_keys=True, default=str)
        checksum = hashlib.sha256(artifact_json.encode()).hexdigest()
        artifact_meta: dict[str, Any] = {
            "experiment_id": experiment_id,
            "checksum": checksum,
            "persisted": False,
            "path": None,
            "format": "json",
            "artifact_status": "not_configured",
        }
        artifact_dir = getattr(self._settings, "forecasting_artifact_dir", None)
        if artifact_dir:
            from pathlib import Path

            d = Path(artifact_dir)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{experiment_id}.json"
            if path.exists():
                artifact_meta["artifact_status"] = "already_exists"
            else:
                try:
                    tmp = d / f".{experiment_id}.json.tmp"
                    tmp.write_text(artifact_json, encoding="utf-8")
                    tmp.replace(path)
                    artifact_meta["persisted"] = True
                    artifact_meta["path"] = str(path)
                    artifact_meta["artifact_status"] = "written"
                except OSError:
                    artifact_meta["artifact_status"] = "failed"

        aggregate = {
            "n_models": len(model_results),
            "n_folds": len(folds),
            "best_model_by_primary": None,
        }
        if model_results:
            if tt == "regression":
                best = min(
                    model_results,
                    key=lambda m: m["aggregate_primary_metric"]
                    if m["aggregate_primary_metric"] == m["aggregate_primary_metric"]
                    else float("inf"),
                )
            else:
                best = max(
                    model_results,
                    key=lambda m: m["aggregate_primary_metric"]
                    if m["aggregate_primary_metric"] == m["aggregate_primary_metric"]
                    else -float("inf"),
                )
            aggregate["best_model_by_primary"] = best["model_family"]

        if not folds:
            warnings.append("insufficient data for walk-forward evaluation")
        if len(y_vals) < 100:
            warnings.append("small sample size limits reliability")

        status = "completed" if folds else "insufficient_data"
        if warnings:
            status = "completed_with_warnings"

        result = {
            "experiment_id": experiment_id,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "problem": dataclasses.asdict(spec),
            "dataset_fingerprint": dataset_fingerprint,
            "data_source": (
                "upstream_historical"
                if getattr(request, "observations", None) is None
                and getattr(request, "instrument", None)
                else "user_supplied_observations"
            ),
            "synthetic": bool(getattr(request, "observations", None) is not None),
            "data_provenance": {
                "instrument": instrument,
                "timeframe": timeframe,
                "user_supplied_observations": bool(
                    getattr(request, "observations", None) is not None
                ),
            },
            "feature_set_version": "1.0.0",
            "target_type": spec.target_type,
            "task_type": tt,
            "n_observations": len(y_vals),
            "n_folds": len(folds),
            "folds": fold_summary,
            "models": model_results,
            "comparison": [
                {
                    "model_family": m["model_family"],
                    "aggregate_primary_metric": m["aggregate_primary_metric"],
                    "baseline_name": m["baseline_name"],
                    "baseline_aggregate_primary": m["baseline_aggregate_primary"],
                    "improvement_vs_baseline": m["improvement_vs_baseline"],
                }
                for m in model_results
            ],
            "aggregate": aggregate,
            "warnings": warnings,
            "limitations": limitations,
            "artifact": artifact_meta,
        }

        self._experiments[experiment_id] = result
        return result

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self) -> list[str]:
        return list(self._experiments.keys())

    async def check_data_source(self, request_id: str) -> dict[str, Any]:
        """Return contract-safe diagnostics for the upstream market-data service."""
        result = await self._upstream.check_connectivity(request_id=request_id)
        return {
            "configuration": {
                "base_url_configured": self._upstream.is_configured,
                "credential_configured": self._upstream.has_credential,
            },
            "connectivity": {
                "state": result.state.value,
                "message": result.message,
                "latency_ms": result.latency_ms,
                "checked_at": result.checked_at,
            },
            "contract_status": result.contract_status.value,
        }

    async def retrieve_historical_dataset(self, request: Any, request_id: str) -> dict[str, Any]:
        """Retrieve and validate a historical dataset through the verified upstream client."""
        import hashlib
        import json

        from backend.app.analysis.data_quality import validate_historical_payload
        from backend.app.analysis.observations import Observation, coerce_timestamp

        instrument = getattr(request, "instrument", None)
        if not instrument:
            from backend.app.core.errors import ValidationError as AppValidationError

            raise AppValidationError("An instrument identifier is required.")
        if not self._upstream.is_configured:
            from backend.app.core.errors import ValidationError as AppValidationError

            raise AppValidationError("Upstream market-data service is not configured.")

        start = getattr(request, "start", None)
        end = getattr(request, "end", None)
        timeframe = getattr(request, "timeframe", None) or "D1"
        price_basis = getattr(request, "price_basis", None) or "bid"
        provider_id = (
            getattr(request, "provider_id", None) or self._settings.upstream_default_provider_id
        )
        limit = getattr(request, "limit", None)
        if limit is None:
            limit = 500
        if limit < 1 or limit > getattr(self._settings, "upstream_max_history_limit", 5000):
            from backend.app.core.errors import ValidationError as AppValidationError

            raise AppValidationError("limit exceeds the permitted historical request bound")

        allowed_start = getattr(self._settings, "upstream_allowed_history_start", None)
        allowed_end = getattr(self._settings, "upstream_allowed_history_end", None)
        if allowed_start is not None and start is not None and start < allowed_start:
            from backend.app.core.errors import ValidationError as AppValidationError

            raise AppValidationError("requested start is before the permitted historical range")
        if allowed_end is not None and end is not None and end > allowed_end:
            from backend.app.core.errors import ValidationError as AppValidationError

            raise AppValidationError("requested end is after the permitted historical range")

        data = await self._upstream.fetch_historical_candles(
            instrument,
            provider_id=provider_id,
            start=start,
            end=end,
            timeframe=timeframe,
            price_basis=price_basis,
            limit=limit,
            request_id=request_id,
        )

        quality = validate_historical_payload(
            data,
            expected_timeframe=timeframe,
            expected_price_basis=price_basis,
        )

        observations: list[Observation] = []
        for candle in data.candles:
            try:
                observations.append(
                    Observation(
                        timestamp=coerce_timestamp(candle.open_time),
                        open=float(candle.open) if candle.open is not None else 0.0,
                        high=float(candle.high) if candle.high is not None else 0.0,
                        low=float(candle.low) if candle.low is not None else 0.0,
                        close=float(candle.close) if candle.close is not None else 0.0,
                        volume=float(candle.volume) if candle.volume is not None else None,
                    )
                )
            except (TypeError, ValueError):
                continue
        observations = sorted(observations, key=lambda o: o.timestamp)

        canonical = {
            "instrument": data.canonical_instrument,
            "timeframe": str(data.timeframe),
            "price_basis": str(data.price_basis),
            "provider_id": data.provider_id,
            "requested_start": data.requested_start.isoformat() if data.requested_start else None,
            "requested_end": data.requested_end.isoformat() if data.requested_end else None,
            "actual_start": data.effective_start.isoformat() if data.effective_start else None,
            "actual_end": data.effective_end.isoformat() if data.effective_end else None,
            "row_count": len(data.candles),
            "retrieved_at": data.retrieved_at.isoformat(),
            "coverage": data.coverage.model_dump(),
        }
        fingerprint = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        provenance = {
            "source_service": "fx-market-data-service",
            "provider_id": data.provider_id,
            "canonical_instrument": data.canonical_instrument,
            "timeframe": str(data.timeframe),
            "price_basis": str(data.price_basis),
            "requested_start": data.requested_start.isoformat() if data.requested_start else None,
            "requested_end": data.requested_end.isoformat() if data.requested_end else None,
            "actual_start": data.effective_start.isoformat() if data.effective_start else None,
            "actual_end": data.effective_end.isoformat() if data.effective_end else None,
            "retrieved_at": data.retrieved_at.isoformat(),
            "row_count": len(data.candles),
            "request_or_correlation_id": request_id,
            "response_schema_version": "verified-service1-historical-v1",
            "source_limitations": list(data.limitations),
            "coverage": data.coverage.model_dump(),
            "validation_summary": data.validation_summary.model_dump(),
            "pagination": data.pagination.model_dump(),
            "dataset_fingerprint": fingerprint,
        }

        return {
            "status": "completed",
            "data_source": "upstream_historical",
            "synthetic": False,
            "instrument": data.canonical_instrument,
            "timeframe": str(data.timeframe),
            "price_basis": str(data.price_basis),
            "provider_id": data.provider_id,
            "observations": [
                {
                    "timestamp": o.timestamp.isoformat(),
                    "open": o.open,
                    "high": o.high,
                    "low": o.low,
                    "close": o.close,
                    "volume": o.volume,
                }
                for o in observations
            ],
            "quality": quality,
            "provenance": provenance,
            "dataset_fingerprint": fingerprint,
            "partial": quality.get("partial", False),
        }

    async def assess_research_readiness(self, request: Any, request_id: str) -> dict[str, Any]:
        """Validate whether a forecasting experiment is ready to run on its data."""
        from backend.app.core.errors import ValidationError as AppValidationError

        valid, errors, config = await self.validate_experiment(request)
        findings: list[dict[str, Any]] = []
        for err in errors:
            findings.append({"severity": "error", "code": "experiment_validation", "message": err})

        observations = getattr(request, "observations", None)
        instrument = getattr(request, "instrument", None)
        dataset_quality = None
        if instrument and not observations:
            try:
                dataset_result = await self.retrieve_historical_dataset(request, request_id)
                dataset_quality = dataset_result.get("quality")
                if dataset_quality and not dataset_quality.get("valid", False):
                    for err in dataset_quality.get("blocking_errors", []):
                        findings.append(
                            {"severity": "error", "code": "dataset_quality", "message": err}
                        )
                for warn in (dataset_quality or {}).get("warnings", []):
                    findings.append(
                        {"severity": "warning", "code": "dataset_quality", "message": warn}
                    )
                if dataset_quality and dataset_quality.get("partial"):
                    findings.append(
                        {
                            "severity": "warning",
                            "code": "partial_dataset",
                            "message": "Dataset is partial and may not satisfy coverage requirements.",
                        }
                    )
                min_required = request.problem.required_historical_coverage
                if len(dataset_result.get("observations", [])) < min_required:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "insufficient_history",
                            "message": "Retrieved observations are below the required historical coverage.",
                        }
                    )
            except AppValidationError as exc:
                findings.append(
                    {"severity": "error", "code": "dataset_retrieval", "message": str(exc)}
                )
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {"severity": "error", "code": "dataset_retrieval", "message": str(exc)}
                )
        else:
            obs = []
            if observations:
                from backend.app.analysis.observations import ensure_sorted, from_mapping

                for raw in observations:
                    obs.append(from_mapping(raw if isinstance(raw, dict) else raw.model_dump()))
                obs = ensure_sorted(obs)
            if len(obs) < getattr(request.problem, "required_historical_coverage", 1):
                findings.append(
                    {
                        "severity": "error",
                        "code": "insufficient_history",
                        "message": "Supplied observations are below the required historical coverage.",
                    }
                )

        has_blocking = any(f["severity"] == "error" for f in findings)
        return {
            "ready": (not has_blocking) and valid,
            "findings": findings,
            "experiment_validation": {"valid": valid, "errors": errors, "config": config},
            "dataset_quality": dataset_quality,
        }
