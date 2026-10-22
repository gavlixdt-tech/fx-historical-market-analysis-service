"""Health-check response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import HealthResponseData


class LiveResponseData(HealthResponseData):
    """Liveness response payload."""

    check: str = Field(default="liveness", description="Type of check performed")


class DependencyHealth(BaseModel):
    """Health of a single dependency."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Dependency identifier")
    healthy: bool = Field(..., description="Whether the dependency is healthy")
    detail: str | None = Field(default=None, description="Additional detail")


class ReadyResponseData(HealthResponseData):
    """Readiness response payload."""

    check: str = Field(default="readiness", description="Type of check performed")
    dependencies: list[DependencyHealth] = Field(
        default_factory=list, description="Dependency health details, if any"
    )
