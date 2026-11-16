"""Verify Service 1's purpose-separated historical candle dataset signatures.

The public-key trust bundle is provisioned out of band. A verified signature
authenticates the configured Service 1 signer and exact response projection;
it does not prove that the upstream vendor digitally signed the market prices.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from backend.app.core.config import Settings
from backend.app.core.errors import UpstreamError


def canonical_json(value: Any) -> bytes:
    """Serialize the signed projection with Service 1's canonical JSON rules."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _encoded_price(value: Any) -> str | None:
    return None if value is None else str(value)


def verify_historical_dataset_attestation(
    *,
    settings: Settings,
    attestation: Any,
    instrument: str,
    timeframe: str,
    provider_id: str,
    candles: list[dict[str, Any]],
    retrieved_at: str,
    effective_price_basis: str,
    coverage: dict[str, Any],
    validation_summary: dict[str, Any],
    limitations: list[Any],
) -> str:
    """Return the attestation state or raise if any signed value is inconsistent."""
    required = settings.upstream_historical_attestation_required or settings.is_production
    if not isinstance(attestation, dict):
        if required:
            raise UpstreamError(
                "Service 1 did not provide the required historical dataset attestation.",
                details={"dependency": "fx-market-data-service", "error_type": "attestation_missing"},
            )
        return "missing"

    expected_attestation_fields = {
        "version", "purpose", "algorithm", "provider_id", "source_id", "key_id",
        "issued_at", "observed_at", "instrument", "timeframe", "dataset_sha256",
        "quality", "volume_semantics", "source_metadata", "signature",
    }
    if (
        set(attestation) != expected_attestation_fields
        or attestation.get("version") != "1"
        or attestation.get("purpose") != "indicator-candle-dataset"
        or attestation.get("algorithm") != "Ed25519"
        or attestation.get("provider_id") != provider_id
        or attestation.get("instrument") != instrument
    ):
        raise UpstreamError(
            "Service 1 historical dataset attestation identity or purpose is invalid.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_identity_invalid"},
        )

    timeframe_map = {
        "M1": "1M",
        "M5": "5M",
        "M15": "15M",
        "M30": "30M",
        "H1": "1H",
        "H4": "4H",
        "D1": "1D",
        "W1": "1W",
        "MN1": "1MO",
    }
    signed_timeframe = attestation.get("timeframe")
    source_metadata = attestation.get("source_metadata")
    quality = attestation.get("quality")
    expected_source_fields = {
        "provider_id", "service1_timeframe", "indicator_timeframe", "price_basis",
        "retrieved_at", "coverage", "validation_summary", "candle_sources",
        "volume_kinds", "limitations",
    }
    expected_quality_fields = {
        "is_final", "valid", "coverage_complete", "rejected_count",
        "duplicate_count", "candle_count",
    }
    if (
        signed_timeframe != timeframe_map.get(timeframe)
        or not isinstance(source_metadata, dict)
        or set(source_metadata) != expected_source_fields
        or not isinstance(quality, dict)
        or set(quality) != expected_quality_fields
        or source_metadata.get("service1_timeframe") != timeframe
        or source_metadata.get("indicator_timeframe") != signed_timeframe
        or source_metadata.get("provider_id") != provider_id
        or source_metadata.get("price_basis") != effective_price_basis
        or canonical_json(source_metadata.get("coverage")) != canonical_json(coverage)
        or canonical_json(source_metadata.get("validation_summary")) != canonical_json(validation_summary)
        or canonical_json(source_metadata.get("limitations")) != canonical_json(limitations)
        or source_metadata.get("retrieved_at") != retrieved_at
        or attestation.get("observed_at") != retrieved_at
        or not isinstance(quality, dict)
        or quality.get("is_final") is not True
        or quality.get("valid") is not True
        or quality.get("coverage_complete") is not True
        or type(quality.get("rejected_count")) is not int
        or quality.get("rejected_count") != 0
        or type(quality.get("duplicate_count")) is not int
        or quality.get("duplicate_count") != 0
        or type(quality.get("candle_count")) is not int
        or quality.get("candle_count") != len(candles)
    ):
        raise UpstreamError(
            "Service 1 historical dataset attestation quality or vintage metadata is inconsistent.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_metadata_mismatch"},
        )

    volume_kinds = sorted({
        raw.get("volume_kind")
        for raw in candles
        if isinstance(raw.get("volume_kind"), str) and raw.get("volume_kind")
    })
    has_volume = any(raw.get("volume") is not None for raw in candles)
    expected_volume_semantics = (
        "not_supplied"
        if not has_volume
        else f"provider_reported:{volume_kinds[0]}"
        if len(volume_kinds) == 1
        else "provider_reported:unknown_or_mixed"
    )
    volume_semantics = attestation.get("volume_semantics")
    if volume_semantics != expected_volume_semantics:
        raise UpstreamError(
            "Service 1 historical attestation volume semantics do not match the candle dataset.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_volume_semantics_invalid"},
        )

    expected_sources = sorted({
        raw.get("source")
        for raw in candles
        if isinstance(raw.get("source"), str) and raw.get("source")
    })
    expected_volume_kinds = sorted({
        raw.get("volume_kind")
        for raw in candles
        if isinstance(raw.get("volume_kind"), str) and raw.get("volume_kind")
    })
    if (
        source_metadata.get("candle_sources") != expected_sources
        or source_metadata.get("volume_kinds") != expected_volume_kinds
    ):
        raise UpstreamError(
            "Service 1 historical dataset source metadata does not match the returned candles.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_source_mismatch"},
        )

    projected: list[dict[str, Any]] = []
    for raw in sorted(candles, key=lambda item: item.get("close_time") or "", reverse=True):
        close_time = raw.get("close_time")
        if not isinstance(close_time, str):
            raise UpstreamError(
                "Attested historical candle is missing close_time.",
                details={"dependency": "fx-market-data-service", "error_type": "attestation_candle_invalid"},
            )
        projected.append({
            "timestamp": close_time.replace("+00:00", "Z"),
            "open": _encoded_price(raw.get("open")),
            "high": _encoded_price(raw.get("high")),
            "low": _encoded_price(raw.get("low")),
            "close": _encoded_price(raw.get("close")),
            "volume": _encoded_price(raw.get("volume")),
        })

    dataset_payload = {
        "instrument": instrument,
        "timeframe": signed_timeframe,
        "candles": projected,
    }
    digest = hashlib.sha256(canonical_json(dataset_payload)).hexdigest()
    if attestation.get("dataset_sha256") != digest:
        raise UpstreamError(
            "Service 1 historical dataset digest does not match the returned candles.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_digest_mismatch"},
        )
    if attestation.get("source_id") != f"historical:{provider_id}:{digest[:24]}":
        raise UpstreamError(
            "Service 1 historical dataset source ID is inconsistent.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_source_id_invalid"},
        )

    try:
        keys = json.loads(settings.upstream_historical_attestation_public_keys_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise UpstreamError(
            "Trusted Service 1 historical attestation key bundle is invalid.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_trust_bundle_invalid"},
        ) from exc
    key_id = attestation.get("key_id")
    encoded_key = keys.get(key_id) if isinstance(keys, dict) and isinstance(key_id, str) else None
    if not isinstance(encoded_key, str):
        if required:
            raise UpstreamError(
                "No trusted Service 1 historical attestation key is configured for this key ID.",
                details={"dependency": "fx-market-data-service", "error_type": "attestation_key_untrusted"},
            )
        return "unverified_key_missing"

    signature_value = attestation.get("signature")
    if not isinstance(signature_value, str) or not signature_value.startswith("ed25519="):
        raise UpstreamError(
            "Service 1 historical dataset signature is malformed.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_signature_malformed"},
        )
    try:
        public_key_bytes = base64.b64decode(encoded_key, validate=True)
        signature = base64.b64decode(signature_value[len("ed25519="):], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise UpstreamError(
            "Trusted Service 1 key or historical signature encoding is invalid.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_encoding_invalid"},
        ) from exc

    signed_payload = {
        key: value for key, value in attestation.items()
        if key not in {"signature", "_dataset_candles"}
    }
    try:
        public_key.verify(signature, canonical_json(signed_payload))
    except InvalidSignature as exc:
        raise UpstreamError(
            "Service 1 historical dataset Ed25519 signature verification failed.",
            details={"dependency": "fx-market-data-service", "error_type": "attestation_signature_invalid"},
        ) from exc
    return "verified"
