"""Historical regime and pattern research endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.schemas.analysis import (
    CapabilityDiscoveryData,
    PatternResearchRequest,
    PatternResearchResponseData,
    RegimeAnalysisRequest,
    RegimeAnalysisResponseData,
)
from backend.app.schemas.common import ApiResponse
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.health_service import build_meta

router = APIRouter()


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service  # type: ignore[no-any-return]


@router.post(
    "/analysis/regimes",
    response_model=ApiResponse[RegimeAnalysisResponseData],
    summary="Regime analysis",
)
async def analyze_regimes(
    request: Request, payload: RegimeAnalysisRequest
) -> ApiResponse[RegimeAnalysisResponseData]:
    service = get_analysis_service(request)
    request_id = getattr(request.state, "request_id", "unknown")
    data = await service.analyze_regimes(payload, request_id=request_id)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, request_id))


@router.post(
    "/analysis/patterns",
    response_model=ApiResponse[PatternResearchResponseData],
    summary="Pattern research",
)
async def research_patterns(
    request: Request, payload: PatternResearchRequest
) -> ApiResponse[PatternResearchResponseData]:
    service = get_analysis_service(request)
    request_id = getattr(request.state, "request_id", "unknown")
    data = await service.research_patterns(payload, request_id=request_id)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, request_id))


@router.get(
    "/analysis/capabilities",
    response_model=ApiResponse[CapabilityDiscoveryData],
    summary="Analysis capabilities",
)
async def capabilities(request: Request) -> ApiResponse[CapabilityDiscoveryData]:
    service = get_analysis_service(request)
    request_id = getattr(request.state, "request_id", "unknown")
    return ApiResponse(
        data=service.capabilities(), meta=build_meta(request.app.state.settings, request_id)
    )
