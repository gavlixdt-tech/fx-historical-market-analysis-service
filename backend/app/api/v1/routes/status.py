"""Service status endpoint - /api/v1/status.

Returns truthful operational status, capabilities, and dependency health.
No sensitive infrastructure details are exposed.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.status import StatusResponseData
from backend.app.services.health_service import HealthService

router = APIRouter()


def get_health_service(request: Request) -> HealthService:
    """Retrieve the HealthService instance stored on the FastAPI app state."""
    return request.app.state.health_service  # type: ignore[no-any-return]


@router.get(
    "/status",
    response_model=ApiResponse[StatusResponseData],
    summary="Service status",
    description="Return operational status, capabilities, and dependency health.",
)
async def service_status(request: Request) -> ApiResponse[StatusResponseData]:
    service = get_health_service(request)
    return await service.status(request_id=getattr(request.state, "request_id", "unknown"))
