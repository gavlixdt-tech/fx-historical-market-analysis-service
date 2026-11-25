"""API contracts for causal market-structure analysis."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.analysis import ObservationInput


class MarketStructureConfigInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    pivot_left: int = Field(default=3, ge=1, le=20)
    pivot_right: int = Field(default=3, ge=1, le=20)
    atr_window: int = Field(default=14, ge=2, le=200)
    equal_level_atr_tolerance: float = Field(default=0.12, gt=0, le=1)
    displacement_atr_multiple: float = Field(default=1.5, gt=0, le=10)
    minimum_range_bars: int = Field(default=12, ge=3, le=500)
    maximum_events: int = Field(default=500, ge=1, le=5000)


class MarketStructureRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    observations: list[ObservationInput] = Field(min_length=20, max_length=5000)
    instrument: str | None = Field(default=None, min_length=1, max_length=32)
    timeframe: str | None = Field(default=None, min_length=1, max_length=16)
    config: MarketStructureConfigInput = Field(default_factory=MarketStructureConfigInput)

    @model_validator(mode="after")
    def chronological(self) -> MarketStructureRequest:
        timestamps = [item.timestamp for item in self.observations]
        if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
            raise ValueError("observations must be strictly chronological and unique")
        return self


class MarketStructureResponseData(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    instrument: str | None = None
    timeframe: str | None = None
    analysis: dict[str, Any]
