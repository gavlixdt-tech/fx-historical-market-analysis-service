"""Version response schemas."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from .common import VersionResponseData

__all__ = ["VersionResponseData"]


class VersionDetails(VersionResponseData):
    """Version payload extended with the operating mode.

    The operating mode is always `research-simulation`; it is surfaced so that
    an operator can confirm at a glance that the deployment cannot trade.
    """

    model_config = ConfigDict(frozen=True)

    service_mode: str = Field(default="research-simulation", description="Operating mode")
