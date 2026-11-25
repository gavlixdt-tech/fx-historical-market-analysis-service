from __future__ import annotations

from backend.app.schemas.instruments import (
    GFX_INSTRUMENT_REGISTRY_VERSION,
    SUPPORTED_GFX_INSTRUMENTS,
    canonicalize_gfx_instrument,
)


def test_historical_instrument_scope_includes_btc_usd_in_registry_v2() -> None:
    assert GFX_INSTRUMENT_REGISTRY_VERSION == "surveillance-instruments/2"
    assert "BTC/USD" in SUPPORTED_GFX_INSTRUMENTS
    assert canonicalize_gfx_instrument("BTC/USD") == "BTC/USD"
    assert canonicalize_gfx_instrument("BTCUSD") == "BTC/USD"
    assert canonicalize_gfx_instrument("btc-usd") == "BTC/USD"


def test_historical_instrument_scope_still_rejects_unregistered_crosses() -> None:
    assert canonicalize_gfx_instrument("EUR/GBP") is None
    assert canonicalize_gfx_instrument("ETH/USD") is None
