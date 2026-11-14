"""Orchestration for historical regime and pattern research."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC
from typing import Any

from backend.app.analysis.change_points import detect_change_points_combined
from backend.app.analysis.data_quality import validate_historical_payload
from backend.app.analysis.observations import (
    Observation,
    ensure_sorted,
    from_mapping,
    validate_minimum,
)
from backend.app.analysis.patterns import (
    PatternSpec,
    apply_overlap_policy,
    baseline_outcomes,
    benjamini_hochberg,
    bootstrap_mean_ci,
    compute_outcomes,
    detect_events,
    permutation_p_value,
    partition_pattern_events,
    walk_forward_indices,
)
from backend.app.analysis.regimes import RegimeConfig, classify_regimes
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.core.errors import ValidationError
from backend.app.schemas.analysis import (
    CapabilityDiscoveryData,
    ObservationInput,
    PatternConfigInput,
    PatternResearchRequest,
    PatternResearchResponseData,
    PatternResult,
    RegimeAnalysisRequest,
    RegimeAnalysisResponseData,
    RegimeConfigInput,
    RegimeSegment,
    ResearchSummaryConfigInput,
    ResearchSummaryData,
    ResearchSummaryRequest,
)
from backend.app.services.market_data_policy import (
    require_approved_real_instrument,
    require_historical_provider,
)


def _obs_from_input(obs: Any) -> Observation:
    if isinstance(obs, dict):
        return from_mapping(obs)
    # pydantic model
    return from_mapping(obs.model_dump())


def _dataset_fingerprint(
    observations: list[Observation], instrument: str | None, timeframe: str | None
) -> str:
    payload = {
        "instrument": instrument,
        "timeframe": timeframe,
        "observations": [
            {
                "timestamp": observation.timestamp.astimezone(UTC).isoformat(),
                "open": observation.open,
                "high": observation.high,
                "low": observation.low,
                "close": observation.close,
                "volume": observation.volume,
            }
            for observation in observations
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _data_provenance(source_quality: dict[str, Any] | None) -> dict[str, Any]:
    if source_quality is None:
        return {
            "provenance_status": "user_supplied_unverified",
            "availability_provenance": "availability_assumed",
            "limitations": [
                "Caller-supplied observations and their timestamps are not independently verified."
            ],
        }
    provider_type = source_quality.get("provider_type")
    return {
        "provenance_status": (
            "synthetic_fixture" if provider_type == "test" else "provider_asserted_unverified"
        ),
        "availability_provenance": "availability_assumed",
        "provider_id": source_quality.get("provider_id"),
        "retrieved_at": source_quality.get("retrieved_at"),
        "limitations": source_quality.get("limitations", []),
    }


def _pattern_definition(pattern_id: str) -> str:
    definitions = {
        "volatility_compression_expansion": (
            "Short-window return volatility is below a configured fraction of "
            "the lookback-window return volatility."
        ),
        "directional_persistence": (
            "All simple returns in the configured lookback window have the same non-zero sign."
        ),
        "reversal_after_large_move": (
            "A return exceeds the configured multiple of lookback volatility and "
            "the preceding cumulative return has the opposite sign."
        ),
    }
    return definitions.get(pattern_id, "No supported definition is registered for this pattern.")


def _pattern_methodology(pattern_id: str, lookback: int) -> str:
    definitions = {
        "volatility_compression_expansion": (
            f"Rolling sample standard deviations of simple close returns; "
            f"short window=min({lookback}, 10), long window={lookback}."
        ),
        "directional_persistence": (
            f"Checks the signs of each of the {lookback} simple close returns."
        ),
        "reversal_after_large_move": (
            f"Compares the latest simple close return with {lookback}-period "
            "sample volatility and the preceding cumulative return."
        ),
    }
    return definitions.get(pattern_id, "No supported detection method is registered.")


class AnalysisService:
    def __init__(self, settings: Settings, upstream_client: MarketDataClient) -> None:
        self._settings = settings
        self._upstream = upstream_client

    async def _resolve_observations(
        self, request: Any, request_id: str
    ) -> tuple[list[Observation], str | None, str | None, dict[str, Any] | None]:
        observations: list[Observation] = []
        if getattr(request, "observations", None):
            for raw in request.observations:
                observations.append(_obs_from_input(raw))
            timestamps = [observation.timestamp for observation in observations]
            if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
                raise ValidationError(
                    "Caller-supplied observations must be strictly chronological and unique."
                )
            return observations, request.instrument, request.timeframe, None
        # upstream fetch
        instrument = request.instrument
        if not instrument:
            raise ValidationError("Either observations or instrument must be provided.")
        if not self._upstream.is_configured:
            raise ValidationError("Upstream market-data service is not configured.")
        provider_id = getattr(request, "provider_id", None)
        provider = await require_historical_provider(
            self._upstream,
            provider_id,
            request_id=request_id,
            environment=self._settings.environment,
        )
        if provider.provider_type.value == "real":
            require_approved_real_instrument(instrument)
        data = await self._upstream.fetch_historical_candles(
            instrument,
            provider_id=provider.provider_id,
            start=request.start,
            end=request.end,
            timeframe=request.timeframe or "D1",
            price_basis=request.price_basis or "bid",
            limit=request.limit or 500,
            request_id=request_id,
        )
        if data.provider_id != provider.provider_id:
            raise ValidationError("Market-data response provider does not match the selection.")
        source_quality = validate_historical_payload(
            data,
            expected_timeframe=request.timeframe or "D1",
            expected_price_basis=request.price_basis or "bid",
        )
        if (
            not source_quality["valid"]
            or not data.coverage.complete
            or data.coverage.rejected_count
            or data.coverage.duplicate_count
            or data.pagination.has_more
        ):
            raise ValidationError(
                "Historical analysis requires complete, untruncated source coverage "
                "without rejected or duplicate observations."
            )
        for c in data.candles:
            if (
                not c.valid
                or c.completeness != "complete"
                or c.open is None
                or c.high is None
                or c.low is None
                or c.close is None
                or c.close_time is None
            ):
                raise ValidationError(
                    "Historical analysis received an invalid or incomplete candle."
                )
            try:
                if c.open_time.tzinfo is None or c.close_time.tzinfo is None:
                    raise ValueError("naive timestamp")
                observations.append(
                    Observation(
                        timestamp=c.open_time.astimezone(UTC),
                        open=float(c.open),
                        high=float(c.high),
                        low=float(c.low),
                        close=float(c.close),
                        volume=float(c.volume) if c.volume is not None else None,
                    )
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValidationError(
                    "Historical analysis received an invalid candle value."
                ) from exc
        observations = ensure_sorted(observations)
        upstream_quality = {
            "provider_id": data.provider_id,
            "provider_type": provider.provider_type.value,
            "retrieved_at": data.retrieved_at.isoformat(),
            "availability_provenance": "availability_assumed",
            "availability_assumption": (
                "Service 1 does not provide original historical publication timestamps."
            ),
            "data_quality": source_quality,
            "validation_summary": data.validation_summary.model_dump(),
            "coverage": data.coverage.model_dump(),
            "limitations": list(data.limitations),
            "row_count": len(data.candles),
        }
        return observations, data.canonical_instrument, str(data.timeframe), upstream_quality

    async def analyze_regimes(
        self, request: RegimeAnalysisRequest, request_id: str
    ) -> RegimeAnalysisResponseData:
        started = time.perf_counter()
        analysis_id = str(uuid.uuid4())
        warnings: list[str] = []
        limitations = [
            "Regime labels are descriptive model outputs, not ground truth.",
            "Change-point detection is retrospective and may not be knowable in real time.",
        ]
        observations, instrument, timeframe, source_quality = await self._resolve_observations(
            request, request_id
        )
        cfg_in: RegimeConfigInput = request.config
        config = RegimeConfig(
            return_window=cfg_in.return_window,
            volatility_window=cfg_in.volatility_window,
            long_volatility_window=cfg_in.long_volatility_window,
            trend_threshold=cfg_in.trend_threshold,
            high_volatility_threshold=cfg_in.high_volatility_threshold,
            low_volatility_threshold=cfg_in.low_volatility_threshold,
            direction_consistency_threshold=cfg_in.direction_consistency_threshold,
            range_bound_consistency=cfg_in.range_bound_consistency,
            min_observations=cfg_in.min_observations,
        )
        validate_minimum(observations, config.min_observations)

        # Status determination.
        status = "completed"
        if len(observations) < config.long_volatility_window:
            warnings.append("Long volatility window exceeds available history; warm-up truncated.")

        regime_obs = classify_regimes(observations, config)
        # change points on returns
        returns = [0.0] + [
            (observations[i].close - observations[i - 1].close) / observations[i - 1].close
            if observations[i - 1].close != 0
            else 0.0
            for i in range(1, len(observations))
        ]
        # drop first for change points? keep aligned length
        series = returns[1:] if len(returns) > 1 else returns
        # pad to same length as observations by using 0 for first
        if len(series) < len(observations):
            series = [0.0] + series
        cps = detect_change_points_combined(
            series,
            min_segment_length=cfg_in.change_point_min_segment,
            max_change_points=cfg_in.change_point_max,
            penalty=cfg_in.change_point_penalty,
        )
        change_point_timestamps = [
            observations[i].timestamp.isoformat() for i in cps if i < len(observations)
        ]

        # segments between change points
        boundaries = [0] + cps + [len(observations)]
        segments: list[RegimeSegment] = []
        for a, b in zip(boundaries, boundaries[1:], strict=False):
            if b - a < 1:
                continue
            seg_obs = observations[a:b]
            seg_returns = list(returns[a + 1 : b] if a + 1 <= b else [])
            # mean return
            mean_ret = (sum(seg_returns) / len(seg_returns)) if seg_returns else None
            vol = None
            if len(seg_returns) >= 2:
                m = sum(seg_returns) / len(seg_returns)
                var = sum((r - m) ** 2 for r in seg_returns) / (len(seg_returns) - 1)
                vol = var**0.5
            cumret = None
            if seg_obs:
                if seg_obs[0].close != 0:
                    cumret = seg_obs[-1].close / seg_obs[0].close - 1.0
            dd = None
            if seg_obs:
                dd = _max_drawdown([o.close for o in seg_obs])
            consistency = None
            if seg_returns:
                signs = [1.0 if r > 0 else (-1.0 if r < 0 else 0.0) for r in seg_returns]
                consistency = sum(signs) / len(signs)
            segments.append(
                RegimeSegment(
                    start_index=a,
                    end_index=b - 1,
                    start_timestamp=observations[a].timestamp.isoformat(),
                    end_timestamp=observations[b - 1].timestamp.isoformat(),
                    observation_count=b - a,
                    mean_return=mean_ret,
                    volatility=vol,
                    cumulative_return=cumret,
                    max_drawdown=dd,
                    direction_consistency=consistency,
                )
            )

        # proportions
        counts: dict[str, int] = {}
        for ro in regime_obs:
            counts[ro.regime] = counts.get(ro.regime, 0) + 1
        total = len(regime_obs) or 1
        proportions = {k: v / total for k, v in counts.items()}
        unclassified = counts.get("unclassified", 0)
        # transition frequenc
        transitions = 0
        for i in range(1, len(regime_obs)):
            if regime_obs[i].regime != regime_obs[i - 1].regime:
                transitions += 1
        tfreq = transitions / max(1, len(regime_obs) - 1)
        short_segments = sum(1 for s in segments if s.observation_count < 5)

        agreement = None
        try:
            cfg2 = RegimeConfig(
                return_window=config.return_window,
                volatility_window=config.volatility_window,
                long_volatility_window=config.long_volatility_window,
                trend_threshold=config.trend_threshold * 1.2,
                high_volatility_threshold=config.high_volatility_threshold,
                low_volatility_threshold=config.low_volatility_threshold,
                direction_consistency_threshold=config.direction_consistency_threshold,
                range_bound_consistency=config.range_bound_consistency,
                min_observations=config.min_observations,
            )
            alt = classify_regimes(observations, cfg2)
            same = sum(1 for a, b in zip(regime_obs, alt, strict=False) if a.regime == b.regime)
            agreement = same / len(regime_obs) if regime_obs else None
        except (ValueError, ArithmeticError) as exc:
            warnings.append(f"Sensitivity comparison was unavailable ({type(exc).__name__}).")

        split = len(observations) // 2
        first_counts: dict[str, int] = {}
        second_counts: dict[str, int] = {}
        for ro in regime_obs[:split]:
            first_counts[ro.regime] = first_counts.get(ro.regime, 0) + 1
        for ro in regime_obs[split:]:
            second_counts[ro.regime] = second_counts.get(ro.regime, 0) + 1
        chrono = {
            "discovery_period_observations": split,
            "evaluation_period_observations": len(observations) - split,
            "first_half_regime_counts": first_counts,
            "second_half_regime_counts": second_counts,
            "note": "Regime proportions compared across chronological halves (no shuffling).",
        }

        timeline = [
            {
                "index": ro.index,
                "timestamp": ro.timestamp,
                "regime": ro.regime,
                "direction": ro.direction,
                "volatility": ro.volatility,
                "cumulative_return": ro.cumulative_return,
                "volatility_value": ro.volatility_value,
                "direction_consistency": ro.direction_consistency,
            }
            for ro in regime_obs
        ]

        duration_ms = (time.perf_counter() - started) * 1000
        return RegimeAnalysisResponseData(
            status=status,
            analysis_id=analysis_id,
            instrument=instrument,
            timeframe=timeframe,
            interval_start=observations[0].timestamp.isoformat() if observations else None,
            interval_end=observations[-1].timestamp.isoformat() if observations else None,
            observation_count=len(observations),
            feature_set_version="1.0.0",
            algorithm_id="rule_based_regime_classification",
            algorithm_version="1.0.0",
            config=cfg_in.model_dump(),
            regime_timeline=timeline,
            segments=segments,
            change_points=change_point_timestamps,
            regime_proportions=proportions,
            unclassified_count=unclassified,
            transition_frequency=tfreq,
            short_segment_count=short_segments,
            sensitivity_agreement=agreement,
            chronological_validation=chrono,
            dataset_fingerprint=_dataset_fingerprint(observations, instrument, timeframe),
            data_provenance=_data_provenance(source_quality),
            source_quality=source_quality,
            warnings=warnings,
            limitations=limitations,
            duration_ms=duration_ms,
        )

    async def research_patterns(
        self, request: PatternResearchRequest, request_id: str
    ) -> PatternResearchResponseData:
        started = time.perf_counter()
        analysis_id = str(uuid.uuid4())
        warnings: list[str] = []
        limitations = [
            "Pattern outcomes are retrospective evaluation labels, not real-time signals.",
            "Overlapping windows are not independent samples.",
        ]
        observations, instrument, timeframe, source_quality = await self._resolve_observations(
            request, request_id
        )
        dataset_fingerprint = _dataset_fingerprint(observations, instrument, timeframe)
        cfg_in: PatternConfigInput = request.config
        validate_minimum(observations, cfg_in.lookback + cfg_in.outcome_horizon + 5)

        specs = [
            PatternSpec(
                pattern_id=pid, lookback=cfg_in.lookback, outcome_horizon=cfg_in.outcome_horizon
            )
            for pid in cfg_in.pattern_ids
        ]
        pattern_events_map: dict[str, list[int]] = {}
        for spec in specs:
            raw_events = detect_events(observations, spec)
            filtered = apply_overlap_policy(
                raw_events, cfg_in.overlap_policy, cfg_in.outcome_horizon, cfg_in.min_gap
            )
            pattern_events_map[spec.pattern_id] = filtered

        results_list: list[PatternResult] = []
        p_values: list[float] = []
        for spec in specs:
            events = pattern_events_map[spec.pattern_id]
            ev_objs = compute_outcomes(
                observations, events, cfg_in.outcome_horizon, pattern_id=spec.pattern_id
            )
            outcome_values = [e.outcome for e in ev_objs if e.outcome is not None]
            excluded = len(ev_objs) - len(outcome_values)
            if len(outcome_values) < spec.min_events:
                warnings.append(
                    f"Pattern {spec.pattern_id}: insufficient eligible events ({len(outcome_values)} < {spec.min_events})."
                )
            base = baseline_outcomes(observations, cfg_in.outcome_horizon, set(events))
            baseline_mean = (sum(base) / len(base)) if base else None
            mean_outcome = (sum(outcome_values) / len(outcome_values)) if outcome_values else None
            effect_size = (
                (mean_outcome - baseline_mean)
                if (mean_outcome is not None and baseline_mean is not None)
                else None
            )
            ci_lower, ci_upper = bootstrap_mean_ci(
                outcome_values,
                n_bootstrap=cfg_in.bootstrap_samples,
                block_size=cfg_in.block_size,
                seed=cfg_in.seed,
                alpha=cfg_in.alpha,
            )
            p_val = permutation_p_value(
                outcome_values, base, n_permutations=cfg_in.permutations, seed=cfg_in.seed
            )
            p_values.append(p_val if not (isinstance(p_val, float) and p_val != p_val) else 1.0)
            train_idx, test_idx = walk_forward_indices(
                len(observations), cfg_in.walk_forward_train_ratio
            )
            split_index = len(train_idx)
            (
                train_events,
                test_events,
                purged_train_events,
                incomplete_test_events,
            ) = partition_pattern_events(
                events,
                split_index=split_index,
                outcome_horizon=cfg_in.outcome_horizon,
                observation_count=len(observations),
            )
            train_outcome_vals = [
                ev.outcome
                for ev in compute_outcomes(
                    observations, train_events, cfg_in.outcome_horizon, pattern_id=spec.pattern_id
                )
                if ev.outcome is not None
            ]
            test_outcome_vals = [
                ev.outcome
                for ev in compute_outcomes(
                    observations, test_events, cfg_in.outcome_horizon, pattern_id=spec.pattern_id
                )
                if ev.outcome is not None
            ]
            wf = {
                "train_observations": len(train_idx),
                "test_observations": len(test_idx),
                "train_event_count": len(train_events),
                "test_event_count": len(test_events),
                "train_events_purged_for_horizon": purged_train_events,
                "test_events_without_full_horizon": incomplete_test_events,
                "training_target_end_exclusive_index": split_index,
                "train_mean_outcome": (sum(train_outcome_vals) / len(train_outcome_vals))
                if train_outcome_vals
                else None,
                "test_mean_outcome": (sum(test_outcome_vals) / len(test_outcome_vals))
                if test_outcome_vals
                else None,
                "stability_note": "Chronological split; no shuffling of time series.",
            }
            if excluded:
                warnings.append(
                    f"Pattern {spec.pattern_id}: {excluded} events excluded (insufficient future horizon)."
                )
            results_list.append(
                PatternResult(
                    pattern_id=spec.pattern_id,
                    pattern_version=spec.version,
                    event_count=len(events),
                    eligible_outcome_count=len(outcome_values),
                    mean_outcome=mean_outcome,
                    baseline_mean_outcome=baseline_mean,
                    effect_size=effect_size,
                    ci_lower=None
                    if (isinstance(ci_lower, float) and ci_lower != ci_lower)
                    else ci_lower,
                    ci_upper=None
                    if (isinstance(ci_upper, float) and ci_upper != ci_upper)
                    else ci_upper,
                    p_value=None if (isinstance(p_val, float) and p_val != p_val) else p_val,
                    q_value=None,
                    significant=False,
                    events=[
                        {
                            "pattern_id": e.pattern_id,
                            "index": e.index,
                            "timestamp": e.timestamp,
                            "outcome": e.outcome,
                            "future_volatility": e.future_volatility,
                        }
                        for e in ev_objs
                    ],
                    walk_forward=wf,
                    warnings=[]
                    if len(outcome_values) >= spec.min_events
                    else ["insufficient_events"],
                    instrument=instrument,
                    timeframe=timeframe,
                    historical_interval={
                        "start": observations[0].timestamp.isoformat() if observations else None,
                        "end": observations[-1].timestamp.isoformat() if observations else None,
                    },
                    pattern_definition=_pattern_definition(spec.pattern_id),
                    detection_methodology=_pattern_methodology(spec.pattern_id, cfg_in.lookback),
                    outcome_definition=(
                        "Close-to-close simple return from the pattern observation "
                        "through the configured evaluation horizon."
                    ),
                    evaluation_horizon=cfg_in.outcome_horizon,
                    baseline_comparison={
                        "method": "mean eligible non-pattern close-to-close return",
                        "sample_count": len(base),
                        "mean_outcome": baseline_mean,
                        "effect_size_difference": effect_size,
                    },
                    statistical_uncertainty={
                        "interval_method": "moving_block_bootstrap",
                        "confidence_level": 1.0 - cfg_in.alpha,
                        "ci_lower": ci_lower,
                        "ci_upper": ci_upper,
                        "permutation_p_value": p_val,
                        "multiple_testing_method": "benjamini_hochberg",
                    },
                    data_quality_restrictions={
                        "source_quality": source_quality,
                        "source_identity_verified": False,
                        "availability_verified": False,
                    },
                    dataset_fingerprint=dataset_fingerprint,
                )
            )

        q_vals = benjamini_hochberg(p_values, alpha=cfg_in.alpha)
        for i, r in enumerate(results_list):
            qv = q_vals[i] if i < len(q_vals) else None
            sig = bool(qv is not None and qv < cfg_in.alpha and r.eligible_outcome_count >= 5)
            results_list[i] = r.model_copy(update={"q_value": qv, "significant": sig})

        status = "completed"
        if not observations:
            status = "insufficient_data"
        duration_ms = (time.perf_counter() - started) * 1000
        return PatternResearchResponseData(
            status=status,
            analysis_id=analysis_id,
            instrument=instrument,
            timeframe=timeframe,
            observation_count=len(observations),
            historical_interval={
                "start": observations[0].timestamp.isoformat() if observations else None,
                "end": observations[-1].timestamp.isoformat() if observations else None,
            },
            dataset_fingerprint=dataset_fingerprint,
            data_provenance=_data_provenance(source_quality),
            source_quality=source_quality,
            feature_set_version="1.0.0",
            algorithm_id="bounded_pattern_research",
            algorithm_version="1.0.0",
            config=cfg_in.model_dump(),
            patterns=results_list,
            multiple_testing_method="benjamini_hochberg",
            hypothesis_count=len(results_list),
            warnings=warnings,
            limitations=limitations,
            duration_ms=duration_ms,
        )

    async def research_summary(
        self, request: ResearchSummaryRequest, request_id: str
    ) -> ResearchSummaryData:
        started = time.perf_counter()
        analysis_id = str(uuid.uuid4())
        observations, instrument, timeframe, source_quality = await self._resolve_observations(
            request, request_id
        )
        dataset_fingerprint = _dataset_fingerprint(observations, instrument, timeframe)
        observation_inputs = [
            ObservationInput(
                timestamp=observation.timestamp,
                open=observation.open,
                high=observation.high,
                low=observation.low,
                close=observation.close,
                volume=observation.volume,
            )
            for observation in observations
        ]
        regime_config: ResearchSummaryConfigInput = request.config
        regime_request = RegimeAnalysisRequest(
            observations=observation_inputs,
            instrument=instrument,
            timeframe=timeframe,
            config=regime_config.regime,
        )
        pattern_request = PatternResearchRequest(
            observations=observation_inputs,
            instrument=instrument,
            timeframe=timeframe,
            config=regime_config.pattern,
        )

        regime_result = await self.analyze_regimes(regime_request, request_id=request_id)
        pattern_result = await self.research_patterns(pattern_request, request_id=request_id)
        provenance = _data_provenance(source_quality)
        regime_result = regime_result.model_copy(
            update={
                "dataset_fingerprint": dataset_fingerprint,
                "data_provenance": provenance,
                "source_quality": source_quality,
            }
        )
        pattern_result = pattern_result.model_copy(
            update={
                "dataset_fingerprint": dataset_fingerprint,
                "data_provenance": provenance,
                "source_quality": source_quality,
                "patterns": [
                    pattern.model_copy(
                        update={
                            "dataset_fingerprint": dataset_fingerprint,
                            "data_quality_restrictions": {
                                "source_quality": source_quality,
                                "source_identity_verified": False,
                                "availability_verified": False,
                            },
                        }
                    )
                    for pattern in pattern_result.patterns
                ],
            }
        )

        dominant_regime = "unknown"
        regime_share = 0.0
        if regime_result.regime_proportions:
            dominant_regime, regime_share = max(
                regime_result.regime_proportions.items(), key=lambda item: item[1]
            )

        recent_returns: list[float] = []
        for index in range(1, len(observations)):
            previous_close = observations[index - 1].close
            current_close = observations[index].close
            if previous_close == 0:
                continue
            recent_returns.append((current_close - previous_close) / previous_close)

        trend_state = "range"
        if recent_returns:
            recent_window = recent_returns[-min(20, len(recent_returns)) :]
            mean_recent_return = sum(recent_window) / len(recent_window)
            threshold = regime_config.regime.trend_threshold
            if mean_recent_return > threshold:
                trend_state = "uptrend"
            elif mean_recent_return < -threshold:
                trend_state = "downtrend"

        volatility_values = [
            segment.volatility
            for segment in regime_result.segments
            if segment.volatility is not None
        ]
        avg_volatility = (
            sum(volatility_values) / len(volatility_values) if volatility_values else 0.0
        )
        if avg_volatility >= regime_config.regime.high_volatility_threshold:
            volatility_state = "elevated"
        elif avg_volatility <= regime_config.regime.low_volatility_threshold:
            volatility_state = "contained"
        else:
            volatility_state = "moderate"

        best_pattern = None
        if pattern_result.patterns:
            best_pattern = max(
                pattern_result.patterns,
                key=lambda item: abs(float(item.effect_size or 0.0)),
            )

        pattern_id = best_pattern.pattern_id if best_pattern else None
        pattern_effect_size = best_pattern.effect_size if best_pattern else None
        pattern_significance = bool(best_pattern and best_pattern.significant)

        effect_text = (
            f"with observed effect size {pattern_effect_size:.4f}"
            if pattern_effect_size is not None
            else "with no estimable effect"
        )
        interval_start = observations[0].timestamp.isoformat() if observations else None
        interval_end = observations[-1].timestamp.isoformat() if observations else None
        narrative = (
            f"Across the analyzed historical interval ({interval_start} to {interval_end}), "
            f"the descriptive regime heuristic most often labelled {dominant_regime} "
            f"({regime_share:.3f} of observations); mean segment volatility was "
            f"{volatility_state} and the recent-window descriptor was {trend_state}. "
            f"The largest tested historical pattern effect was "
            f"{pattern_id or 'not estimable'} {effect_text}. These are retrospective "
            "descriptions, not forecasts."
        )
        recommendations = [
            "Prespecify a separate chronological holdout before testing whether these historical descriptions replicate.",
            "Treat pattern significance as exploratory and retain the reported sample counts and multiple-testing correction.",
            "Do not interpret this retrospective summary as a forecast or trading instruction.",
        ]
        limitations = [
            "Historical regime labels are heuristic descriptions, not ground truth or future regime forecasts.",
            "Pattern effects and significance are exploratory and do not establish predictive value.",
            "No calibrated confidence or probability is produced.",
            "Source identity and historical availability are not independently verified.",
        ]
        warnings = list(regime_result.warnings) + list(pattern_result.warnings)
        if source_quality:
            warnings.extend(source_quality.get("data_quality", {}).get("warnings", []))

        duration_ms = (time.perf_counter() - started) * 1000
        return ResearchSummaryData(
            status="completed" if observations else "insufficient_data",
            analysis_id=analysis_id,
            instrument=instrument,
            timeframe=timeframe,
            observation_count=len(observations),
            dominant_regime=dominant_regime,
            regime_share=regime_share,
            volatility_state=volatility_state,
            trend_state=trend_state,
            pattern_id=pattern_id,
            pattern_effect_size=pattern_effect_size,
            pattern_significance=pattern_significance,
            confidence=None,
            confidence_status="not_calculated",
            narrative=narrative,
            recommendations=recommendations,
            regime_summary=regime_result.model_dump(mode="json"),
            pattern_summary=pattern_result.model_dump(mode="json"),
            historical_interval={"start": interval_start, "end": interval_end},
            dataset_fingerprint=dataset_fingerprint,
            data_provenance=provenance,
            source_quality=source_quality,
            warnings=warnings,
            limitations=limitations,
            duration_ms=duration_ms,
        )

    def capabilities(self) -> CapabilityDiscoveryData:
        return CapabilityDiscoveryData(
            algorithms=[
                "rule_based_regime_classification",
                "binary_segmentation_change_points",
                "bounded_pattern_research",
            ],
            features=[
                "simple_returns",
                "log_returns",
                "rolling_mean",
                "rolling_std",
                "cumulative_return",
                "direction_consistency",
                "candle_range_pct",
                "candle_body_ratio",
            ],
            patterns=[
                "volatility_compression_expansion",
                "directional_persistence",
                "reversal_after_large_move",
            ],
            notes=[
                "Retrospective research only; no forecasting or trading signals.",
            ],
        )


def _max_drawdown(closes: list[float]) -> float:
    if not closes:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak != 0:
            dd = (peak - c) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd
