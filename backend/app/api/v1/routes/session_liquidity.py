"""Point-in-time session-conditioned liquidity event studies (research only)."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.common import ApiResponse
from backend.app.services.health_service import build_meta

router = APIRouter()

SessionKey = Literal[
    "wellington", "sydney", "tokyo", "hong_kong", "singapore",
    "frankfurt", "london", "new_york", "sydney_tokyo_overlap",
    "tokyo_london_overlap", "london_new_york_overlap",
    "ict_asia", "ict_london", "ict_new_york_am", "ict_london_close",
    "ict_new_york_pm",
]


class LiquidityEventObservation(BaseModel):
    """A caller-supplied event with explicit right-censoring and availability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(min_length=3, max_length=20)
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    session_key: SessionKey
    session_instance_id: str = Field(min_length=1, max_length=160)
    source_event_id: str = Field(min_length=1, max_length=200)
    direction: Literal["bullish", "bearish"]
    session_open_at: datetime
    sweep_confirmed_at: datetime
    available_at: datetime
    observation_end_at: datetime
    displacement_confirmed_at: datetime | None = None
    midpoint_first_reached_at: datetime | None = None
    consolidation_candidate_at: datetime | None = None
    invalidated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_event_chronology(self) -> LiquidityEventObservation:
        fields = (
            "session_open_at", "sweep_confirmed_at", "available_at",
            "observation_end_at", "displacement_confirmed_at",
            "midpoint_first_reached_at", "consolidation_candidate_at",
            "invalidated_at",
        )
        for name in fields:
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must include an explicit timezone")
        opened = self.session_open_at
        swept = self.sweep_confirmed_at
        ended = self.observation_end_at
        available = self.available_at
        if not opened <= swept <= ended:
            raise ValueError("session_open_at <= sweep_confirmed_at <= observation_end_at is required")
        if available < swept or available > ended:
            raise ValueError("available_at must be between sweep confirmation and observation end")
        transitions = (
            ("displacement_confirmed_at", self.displacement_confirmed_at),
            ("midpoint_first_reached_at", self.midpoint_first_reached_at),
            ("consolidation_candidate_at", self.consolidation_candidate_at),
            ("invalidated_at", self.invalidated_at),
        )
        previous = swept
        for name, value in transitions:
            if value is not None:
                if value < previous or value > ended:
                    raise ValueError(f"{name} must be chronological and no later than observation_end_at")
                previous = value
        if self.midpoint_first_reached_at is not None and self.displacement_confirmed_at is None:
            raise ValueError("midpoint_first_reached_at requires displacement_confirmed_at")
        if self.consolidation_candidate_at is not None and self.midpoint_first_reached_at is None:
            raise ValueError("consolidation_candidate_at requires midpoint_first_reached_at")
        known_transitions = [value for _, value in transitions if value is not None]
        if known_transitions and available < max(known_transitions):
            raise ValueError("available_at cannot precede a supplied lifecycle transition")
        return self


class SessionLiquidityEventStudyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_cutoff: datetime
    events: list[LiquidityEventObservation] = Field(min_length=1, max_length=10000)
    minimum_group_sample: int = Field(default=30, ge=5, le=1000)

    @model_validator(mode="after")
    def validate_cutoff(self) -> SessionLiquidityEventStudyRequest:
        if self.analysis_cutoff.tzinfo is None or self.analysis_cutoff.utcoffset() is None:
            raise ValueError("analysis_cutoff must include an explicit timezone")
        ids = [event.source_event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("source_event_id values must be unique")
        return self


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def _kaplan_meier(
    durations: list[float], observed: list[bool]
) -> dict[str, Any]:
    """Estimate time-to-transition with right-censored observations."""
    if len(durations) != len(observed) or not durations:
        return {"n": 0, "events": 0, "censored": 0, "median_minutes": None, "p90_minutes": None}
    timeline = sorted(set(durations))
    at_risk = len(durations)
    survival = 1.0
    median: float | None = None
    p90: float | None = None
    points: list[dict[str, float | int]] = []
    for instant in timeline:
        failures = sum(d == instant and event for d, event in zip(durations, observed, strict=True))
        censored = sum(d == instant and not event for d, event in zip(durations, observed, strict=True))
        if failures and at_risk:
            survival *= 1.0 - failures / at_risk
            if median is None and survival <= 0.5:
                median = instant
            if p90 is None and survival <= 0.1:
                p90 = instant
            points.append({"minutes": round(instant, 3), "survival": round(survival, 6), "at_risk": at_risk})
        at_risk -= failures + censored
    return {
        "n": len(durations),
        "events": sum(observed),
        "censored": len(observed) - sum(observed),
        "median_minutes": round(median, 3) if median is not None else None,
        "p90_minutes": round(p90, 3) if p90 is not None else None,
        "survival_curve": points,
        "method": "Kaplan-Meier with right censoring",
    }


def _transition_study(
    rows: list[LiquidityEventObservation],
    transition_name: str,
    cutoff: datetime,
) -> dict[str, Any]:
    durations: list[float] = []
    observed: list[bool] = []
    for row in rows:
        transition = getattr(row, transition_name)
        event_observed = transition is not None and transition <= cutoff
        end = transition if event_observed else min(row.observation_end_at, cutoff)
        durations.append(max(0.0, (end - row.sweep_confirmed_at).total_seconds() / 60.0))
        observed.append(event_observed)
    return _kaplan_meier(durations, observed)


def build_session_liquidity_event_study(
    payload: SessionLiquidityEventStudyRequest,
) -> dict[str, Any]:
    """Summarise first confirmed sweep timing and post-sweep transitions by session."""
    cutoff = payload.analysis_cutoff
    eligible = [event for event in payload.events if event.available_at <= cutoff]
    excluded = len(payload.events) - len(eligible)

    # A session instance is the unit of analysis. Keep its earliest confirmed sweep.
    instances: dict[str, LiquidityEventObservation] = {}
    instance_identity: dict[str, tuple[str, str, str, datetime]] = {}
    for event in eligible:
        identity = (event.instrument, event.timeframe, event.session_key, event.session_open_at)
        prior_identity = instance_identity.setdefault(event.session_instance_id, identity)
        if prior_identity != identity:
            raise ValueError("session_instance_id cannot refer to multiple instruments, timeframes, sessions or opens")
        current = instances.get(event.session_instance_id)
        if current is None or event.sweep_confirmed_at < current.sweep_confirmed_at:
            instances[event.session_instance_id] = event

    grouped: dict[tuple[str, str, str], list[LiquidityEventObservation]] = defaultdict(list)
    for event in instances.values():
        grouped[(event.instrument, event.timeframe, event.session_key)].append(event)

    groups: list[dict[str, Any]] = []
    for (instrument, timeframe, session), rows in sorted(grouped.items()):
        rows.sort(key=lambda item: item.sweep_confirmed_at)
        minutes_to_first_sweep = [
            (row.sweep_confirmed_at - row.session_open_at).total_seconds() / 60.0
            for row in rows
        ]
        directional_counts = {
            direction: sum(row.direction == direction for row in rows)
            for direction in ("bullish", "bearish")
        }
        groups.append({
            "instrument": instrument,
            "timeframe": timeframe,
            "session_key": session,
            "first_sweep_session_instances": len(rows),
            "sample_status": "sufficient_for_descriptive_estimate"
                if len(rows) >= payload.minimum_group_sample else "insufficient_sample",
            "minutes_from_session_open_to_first_confirmed_sweep": {
                "median": _percentile(minutes_to_first_sweep, 0.50),
                "p75": _percentile(minutes_to_first_sweep, 0.75),
                "p90": _percentile(minutes_to_first_sweep, 0.90),
                "minimum": round(min(minutes_to_first_sweep), 3),
                "maximum": round(max(minutes_to_first_sweep), 3),
            },
            "first_sweep_direction_counts": directional_counts,
            "post_sweep_time_to_displacement": _transition_study(rows, "displacement_confirmed_at", cutoff),
            "post_sweep_time_to_midpoint": _transition_study(rows, "midpoint_first_reached_at", cutoff),
            "post_sweep_time_to_consolidation_candidate": _transition_study(rows, "consolidation_candidate_at", cutoff),
            "post_sweep_time_to_invalidation": _transition_study(rows, "invalidated_at", cutoff),
            "source_event_ids": [row.source_event_id for row in rows],
        })

    fingerprint_input = {
        "cutoff": cutoff.isoformat(),
        "events": [event.model_dump(mode="json") for event in payload.events],
        "minimum_group_sample": payload.minimum_group_sample,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return {
        "status": "completed" if groups else "no_eligible_events",
        "analysis_id": fingerprint,
        "analysis_cutoff": cutoff.isoformat(),
        "input_event_count": len(payload.events),
        "eligible_event_count": len(eligible),
        "excluded_after_cutoff_count": excluded,
        "first_sweep_session_instance_count": len(instances),
        "groups": groups,
        "provenance_status": "caller_asserted_unverified",
        "limitations": [
            "This is a descriptive event study, not a forward forecast or trading recommendation.",
            "The first sweep is the earliest supplied confirmed sweep per session_instance_id; completeness of supplied events is not independently verified.",
            "Event timestamps, session labels, observation_end_at and source references are caller supplied and not cryptographically authenticated.",
            "Kaplan-Meier estimates assume non-informative right censoring; this assumption must be assessed for each dataset.",
            "Session-specific distributions require sufficient instrument-specific samples and out-of-sample validation before use as model features.",
            "A confirmed OHLC sweep is not proof of resting stop orders or actual order-book liquidity consumption.",
        ],
        "forecast_eligible": False,
    }


@router.post("/market-session-liquidity/event-study")
async def session_liquidity_event_study(
    request: Request, payload: SessionLiquidityEventStudyRequest
) -> ApiResponse[dict[str, Any]]:
    """Return session-conditioned first-sweep and post-sweep timing distributions."""
    from backend.app.core.errors import ValidationError as AppValidationError

    try:
        data = build_session_liquidity_event_study(payload)
    except ValueError as exc:
        raise AppValidationError(str(exc)) from exc
    request_id = getattr(request.state, "request_id", "unknown")
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, request_id))
