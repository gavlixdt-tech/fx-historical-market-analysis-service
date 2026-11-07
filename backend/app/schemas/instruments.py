"""Canonical GFX instrument scope sourced from Service 1's registry."""

from __future__ import annotations

import re

GFX_INSTRUMENT_REGISTRY_VERSION = "surveillance-instruments/1"
SUPPORTED_GFX_INSTRUMENTS = frozenset(
    {
        "XAU/USD",
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "USD/CHF",
        "USD/CAD",
        "AUD/USD",
        "NZD/USD",
    }
)


def canonicalize_gfx_instrument(instrument: str) -> str | None:
    """Return a canonical slash-delimited supported instrument identifier."""
    candidate = instrument.strip().upper().replace("_", "/").replace("-", "/")
    if "/" not in candidate and re.fullmatch(r"[A-Z]{6}", candidate):
        candidate = f"{candidate[:3]}/{candidate[3:]}"
    if candidate in SUPPORTED_GFX_INSTRUMENTS:
        return candidate
    return None
