"""Version endpoint - /api/v1/version.

Returns application and API version information. No external dependencies.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.version import VersionDetails
from backend.app.services.health_service import HealthService

router = APIRouter()


def get_health_service(request: Request) -> HealthService:
    """Retrieve the HealthService instance stored on the FastAPI app state."""
    return request.app.state.health_service  # type: ignore[no-any-return]


@router.get(
    "/version",
    response_model=ApiResponse[VersionDetails],
    summary="Version information",
    description="Return application version and API version information.",
)
async def version(request: Request) -> ApiResponse[VersionDetails]:
    service = get_health_service(request)
    return await service.version(request_id=getattr(request.state, "request_id", "unknown"))
