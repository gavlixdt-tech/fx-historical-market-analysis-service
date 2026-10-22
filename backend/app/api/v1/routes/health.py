"""Health endpoints - /api/v1/health/live and /api/v1/health/ready.

Liveness confirms the process is alive (no external dependency checks).
Readiness confirms the service can accept traffic (includes dependency health).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.health import LiveResponseData, ReadyResponseData
from backend.app.services.health_service import HealthService

router = APIRouter()


def get_health_service(request: Request) -> HealthService:
    """Retrieve the HealthService instance stored on the FastAPI app state."""
    return request.app.state.health_service  # type: ignore[no-any-return]


@router.get(
    "/live",
    response_model=ApiResponse[LiveResponseData],
    summary="Liveness check",
    description="Confirm the backend process is alive. No external dependencies.",
)
async def live(request: Request) -> ApiResponse[LiveResponseData]:
    service = get_health_service(request)
    return await service.liveness(request_id=getattr(request.state, "request_id", "unknown"))


@router.get(
    "/ready",
    response_model=ApiResponse[ReadyResponseData],
    summary="Readiness check",
    description="Confirm the service can accept traffic. Includes dependency health.",
)
async def ready(request: Request, response: Response) -> ApiResponse[ReadyResponseData]:
    service = get_health_service(request)
    result = await service.readiness(request_id=getattr(request.state, "request_id", "unknown"))
    # Readiness returning 'degraded' maps to 503 so infrastructure probes can
    # detect that the service is not fully ready.
    if result.data is not None and result.data.status == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
