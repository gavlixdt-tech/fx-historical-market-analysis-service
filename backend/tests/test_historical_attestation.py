from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.app.clients.historical_attestation import (
    canonical_json,
    verify_historical_dataset_attestation,
)
from backend.app.core.config import Settings
from backend.app.core.errors import UpstreamError


def _fixture():
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_encoded = base64.b64encode(public_bytes).decode("ascii")
    retrieved_at = "2026-11-16T10:00:00Z"
    raw_candles = [{
        "close_time": "2026-11-15T00:00:00Z",
        "open": "1.1000",
        "high": "1.1100",
        "low": "1.0900",
        "close": "1.1050",
        "volume": None,
        "source": "twelve-data",
        "volume_kind": None,
        "price_basis": "vendor_defined",
    }]
    projected = [{
        "timestamp": "2026-11-15T00:00:00Z",
        "open": "1.1000",
        "high": "1.1100",
        "low": "1.0900",
        "close": "1.1050",
        "volume": None,
    }]
    digest = hashlib.sha256(
        canonical_json({"instrument": "EUR/USD", "timeframe": "1D", "candles": projected})
    ).hexdigest()
    source_metadata = {
        "provider_id": "twelve-data",
        "service1_timeframe": "D1",
        "indicator_timeframe": "1D",
        "price_basis": "vendor_defined",
        "retrieved_at": retrieved_at,
        "coverage": {
            "complete": True,
            "status": "complete",
            "returned_count": 1,
            "valid_count": 1,
            "rejected_count": 0,
            "duplicate_count": 0,
            "missing_intervals": [],
        },
        "validation_summary": {"valid": 1, "rejected": 0, "duplicates": 0},
        "candle_sources": ["twelve-data"],
        "volume_kinds": [],
        "limitations": [],
    }
    attestation = {
        "version": "1",
        "purpose": "indicator-candle-dataset",
        "algorithm": "Ed25519",
        "provider_id": "twelve-data",
        "source_id": f"historical:twelve-data:{digest[:24]}",
        "key_id": "svc1-historical-2026-01",
        "issued_at": retrieved_at,
        "observed_at": retrieved_at,
        "instrument": "EUR/USD",
        "timeframe": "1D",
        "dataset_sha256": digest,
        "quality": {
            "is_final": True,
            "valid": True,
            "coverage_complete": True,
            "rejected_count": 0,
            "duplicate_count": 0,
            "candle_count": 1,
        },
        "volume_semantics": "not_supplied",
        "source_metadata": source_metadata,
    }
    attestation["signature"] = "ed25519=" + base64.b64encode(
        private_key.sign(canonical_json(attestation))
    ).decode("ascii")
    settings = Settings(
        upstream_historical_attestation_public_keys_json=(
            '{"svc1-historical-2026-01":"' + public_encoded + '"}'
        ),
        upstream_historical_attestation_required=True,
    )
    return settings, attestation, raw_candles, retrieved_at


def _verify(settings, attestation, candles, retrieved_at, coverage=None):
    metadata = attestation["source_metadata"] if isinstance(attestation, dict) else {}
    return verify_historical_dataset_attestation(
        settings=settings,
        attestation=attestation,
        instrument="EUR/USD",
        timeframe="D1",
        provider_id="twelve-data",
        candles=candles,
        retrieved_at=retrieved_at,
        effective_price_basis="vendor_defined",
        coverage=coverage if coverage is not None else metadata.get("coverage", {}),
        validation_summary=metadata.get("validation_summary", {}),
        limitations=metadata.get("limitations", []),
    )


def test_valid_service1_historical_attestation_is_verified() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    assert _verify(settings, attestation, candles, retrieved_at) == "verified"


def test_tampered_historical_candle_is_rejected() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    candles[0]["close"] = "1.2000"
    with pytest.raises(UpstreamError, match="digest"):
        _verify(settings, attestation, candles, retrieved_at)


def test_unknown_signing_key_fails_closed_when_required() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    settings = Settings(upstream_historical_attestation_required=True)
    with pytest.raises(UpstreamError, match="No trusted"):
        _verify(settings, attestation, candles, retrieved_at)


def test_missing_attestation_is_reported_in_non_production_mode() -> None:
    settings, _, candles, retrieved_at = _fixture()
    settings = Settings(upstream_historical_attestation_required=False)
    assert _verify(settings, None, candles, retrieved_at) == "missing"


def test_modified_coverage_is_rejected_even_when_candles_are_unchanged() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    changed = dict(attestation["source_metadata"]["coverage"])
    changed["complete"] = False
    with pytest.raises(UpstreamError, match="quality or vintage metadata"):
        _verify(settings, attestation, candles, retrieved_at, coverage=changed)


def test_modified_price_basis_is_rejected() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    with pytest.raises(UpstreamError, match="quality or vintage metadata"):
        verify_historical_dataset_attestation(
            settings=settings,
            attestation=attestation,
            instrument="EUR/USD",
            timeframe="D1",
            provider_id="twelve-data",
            candles=candles,
            retrieved_at=retrieved_at,
            effective_price_basis="midpoint",
            coverage=attestation["source_metadata"]["coverage"],
            validation_summary=attestation["source_metadata"]["validation_summary"],
            limitations=attestation["source_metadata"]["limitations"],
        )



def test_invalid_ed25519_signature_is_rejected() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    attestation["signature"] = "ed25519=" + base64.b64encode(b"x" * 64).decode("ascii")
    with pytest.raises(UpstreamError, match="signature verification failed"):
        _verify(settings, attestation, candles, retrieved_at)


def test_unrecognized_attestation_field_is_rejected() -> None:
    settings, attestation, candles, retrieved_at = _fixture()
    attestation["unreviewed_claim"] = True
    with pytest.raises(UpstreamError, match="identity or purpose is invalid"):
        _verify(settings, attestation, candles, retrieved_at)
