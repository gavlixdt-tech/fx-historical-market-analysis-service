"""Historical analogue retrieval endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.historical_analogues import (
    HistoricalAnalogueRequest,
    HistoricalAnalogueResponseData,
)
from backend.app.services.health_service import build_meta
from backend.app.services.historical_analogue_service import HistoricalAnalogueService

router = APIRouter()


@router.post(
    "/analysis/historical-analogues",
    response_model=ApiResponse[HistoricalAnalogueResponseData],
    summary="Leakage-safe historical analogue retrieval and outcome comparison",
)
async def historical_analogues(
    request: Request,
    payload: HistoricalAnalogueRequest,
) -> ApiResponse[HistoricalAnalogueResponseData]:
    service: HistoricalAnalogueService = request.app.state.historical_analogue_service
    request_id = getattr(request.state, "request_id", "unknown")
    data = await service.retrieve(payload, request_id=request_id)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, request_id))
