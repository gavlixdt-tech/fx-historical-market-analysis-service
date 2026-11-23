"""Causal market-structure extraction endpoint."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from backend.app.analysis.market_structure import StructureConfig, analyze_market_structure
from backend.app.analysis.observations import from_mapping
from backend.app.core.errors import ValidationError
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.market_structure import MarketStructureRequest, MarketStructureResponseData
from backend.app.services.health_service import build_meta

router = APIRouter()


@router.post(
    "/analysis/market-structure",
    response_model=ApiResponse[MarketStructureResponseData],
    summary="Causal multi-pattern OHLC market-structure analysis",
)
async def market_structure(
    request: Request, payload: MarketStructureRequest
) -> ApiResponse[MarketStructureResponseData]:
    started = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        observations = [from_mapping(item.model_dump()) for item in payload.observations]
        config = StructureConfig(**payload.config.model_dump())
        analysis = analyze_market_structure(observations, config)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    analysis["instrument"] = payload.instrument
    analysis["timeframe"] = payload.timeframe
    analysis["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    data = MarketStructureResponseData(
        status="completed",
        instrument=payload.instrument,
        timeframe=payload.timeframe,
        analysis=analysis,
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, request_id))
