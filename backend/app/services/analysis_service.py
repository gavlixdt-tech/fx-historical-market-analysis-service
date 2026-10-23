"""Orchestration for historical regime and pattern research."""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.app.analysis.change_points import detect_change_points_combined
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
    walk_forward_indices,
)
from backend.app.analysis.regimes import RegimeConfig, classify_regimes
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.core.errors import ValidationError
from backend.app.schemas.analysis import (
    CapabilityDiscoveryData,
    PatternConfigInput,
    PatternResearchRequest,
    PatternResearchResponseData,
    PatternResult,
    RegimeAnalysisRequest,
    RegimeAnalysisResponseData,
    RegimeConfigInput,
    RegimeSegment,
)


def _obs_from_input(obs: Any) -> Observation:
    if isinstance(obs, dict):
        return from_mapping(obs)
    # pydantic model
    return from_mapping(obs.model_dump())


class AnalysisService:
    def __init__(self, settings: Settings, upstream_client: MarketDataClient) -> None:
        self._settings = settings
        self._upstream = upstream_client

    async def _resolve_observations(
        self, request: Any, request_id: str
    ) -> tuple[list[Observation], str | None, str | None]:
        observations: list[Observation] = []
        if getattr(request, "observations", None):
            for raw in request.observations:
                observations.append(_obs_from_input(raw))
            observations = ensure_sorted(observations)
            return observations, request.instrument, request.timeframe
        # upstream fetch
        instrument = request.instrument
        if not instrument:
            raise ValidationError("Either observations or instrument must be provided.")
        if not self._upstream.is_configured:
            raise ValidationError("Upstream market-data service is not configured.")
        data = await self._upstream.fetch_historical_candles(
            instrument,
            provider_id=request.provider_id or "test-adapter",
            start=request.start,
            end=request.end,
            timeframe=request.timeframe or "D1",
            price_basis=request.price_basis or "bid",
            limit=request.limit or 500,
            request_id=request_id,
        )
        for c in data.candles:
            if c.open is None or c.high is None or c.low is None or c.close is None:
                continue
            try:
                observations.append(
                    Observation(
                        timestamp=c.open_time,
                        open=float(c.open),
                        high=float(c.high),
                        low=float(c.low),
                        close=float(c.close),
                        volume=float(c.volume) if c.volume is not None else None,
                    )
                )
            except (TypeError, ValueError):
                continue
        observations = ensure_sorted(observations)
        return observations, data.canonical_instrument, str(data.timeframe)

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
        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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
        except Exception:  # noqa: BLE001
            agreement = None

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
        observations, instrument, timeframe = await self._resolve_observations(request, request_id)
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
            train_set = set(train_idx)
            test_set = set(test_idx)
            train_events = [e for e in events if e in train_set]
            test_events = [e for e in events if e in test_set]
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
