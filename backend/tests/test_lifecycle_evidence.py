from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import rfc8785
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from backend.app.clients.lifecycle_evidence import (
    LifecycleEvidenceError,
    LifecycleEvidenceInbox,
    verify_lifecycle_event,
)


def signed_envelope(
    private_key: Ed25519PrivateKey,
    *,
    event_id: str = "lifecycle-1",
    state: str = "DISPLACEMENT_CONFIRMED",
    reverse_temporal_order: bool = False,
) -> tuple[dict, str]:
    now = datetime.now(UTC).replace(microsecond=0)
    source_at = now - timedelta(minutes=4)
    observed_at = now - timedelta(minutes=2)
    confirmed_at = now - timedelta(minutes=2)
    if reverse_temporal_order:
        source_at = now
        observed_at = now - timedelta(minutes=2)
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "service9-ed25519-test"
    data = {
        "contract_version": "liquidity-lifecycle-evidence/v1",
        "event_id": event_id,
        "event_type": "com.gavlix.market.liquidity.lifecycle.v1",
        "producer": {
            "service_id": "fx-liquidity-analysis-service",
            "service_number": 9,
            "instance_id": "service9-test-instance",
        },
        "instrument": {
            "canonical_id": "EURUSD",
            "base_currency": "EUR",
            "quote_currency": "USD",
        },
        "timeframe": "1m",
        "lifecycle": {
            "lifecycle_id": event_id,
            "sweep_event_id": "sweep-1",
            "state": state,
            "direction": "BEARISH",
            "anchor_price": "1.1",
            "algorithm": "causal-post-sweep-lifecycle",
            "algorithm_version": "1.0.0",
            "classification_reasons": ["observed close confirmed displacement"],
        },
        "temporal": {
            "source_candle_at": source_at.isoformat().replace("+00:00", "Z"),
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "confirmed_at": confirmed_at.isoformat().replace("+00:00", "Z"),
            "produced_at": now.isoformat().replace("+00:00", "Z"),
            "available_at": now.isoformat().replace("+00:00", "Z"),
            "published_at": None,
            "replay_cutoff_at": None,
        },
        "market_basis": {
            "price_basis": "VENDOR_DEFINED",
            "source_id": "service1:twelve-data",
            "source_timezone": "UTC",
        },
        "quality": {
            "evidence_class": "DERIVED",
            "quality_status": "UNKNOWN",
            "freshness_status": "FRESH",
            "uncertainty_status": "UNQUANTIFIED",
            "limitations": ["source market data is not independently attested"],
        },
        "provenance": {
            "source_event_id": "sweep-1",
            "source_payload_sha256": "a" * 64,
            "lineage": [{
                "service_id": "fx-liquidity-analysis-service",
                "artifact_id": "causal-post-sweep-lifecycle",
                "artifact_version": "1.0.0",
            }],
        },
        "correlation": {
            "correlation_id": event_id,
            "causation_id": "sweep-1",
            "traceparent": None,
        },
    }
    digest = hashlib.sha256(rfc8785.dumps(data)).hexdigest()
    data["integrity"] = {
        "canonicalization": "RFC8785",
        "payload_sha256": digest,
        "signature_algorithm": "Ed25519",
        "key_id": key_id,
        "signature": base64.b64encode(
            private_key.sign(bytes.fromhex(digest))
        ).decode("ascii"),
        "signed_at": now.isoformat().replace("+00:00", "Z"),
    }
    envelope = {
        "id": event_id,
        "type": "com.gavlix.market.liquidity.lifecycle.v1",
        "producer_id": "fx-liquidity-analysis-service",
        "schema_version": "liquidity-lifecycle-evidence/v1",
        "data": data,
    }
    trust = json.dumps({key_id: base64.b64encode(public_raw).decode("ascii")})
    return envelope, trust


def test_verifies_service9_ed25519_signature_and_temporal_contract() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust = signed_envelope(private_key)
    result = verify_lifecycle_event(envelope, public_keys_json=trust)
    assert result["signature_verified"] is True
    assert result["source_verified"] is False
    assert result["instrument"] == "EURUSD"
    assert result["timeframe"] == "1m"


def test_rejects_payload_tampering_after_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust = signed_envelope(private_key)
    envelope["data"]["lifecycle"]["state"] = "INVALIDATED"
    with pytest.raises(LifecycleEvidenceError, match="payload_digest_mismatch"):
        verify_lifecycle_event(envelope, public_keys_json=trust)


def test_rejects_unknown_signing_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust = signed_envelope(private_key)
    envelope["data"]["integrity"]["key_id"] = "untrusted-key"
    with pytest.raises(LifecycleEvidenceError, match="signing_key_untrusted"):
        verify_lifecycle_event(envelope, public_keys_json=trust)


def test_rejects_non_monotonic_event_timestamps_even_with_valid_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust = signed_envelope(private_key, reverse_temporal_order=True)
    with pytest.raises(LifecycleEvidenceError, match="temporal_order_invalid"):
        verify_lifecycle_event(envelope, public_keys_json=trust)


def test_durable_inbox_deduplicates_and_records_event_id_conflicts(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(envelope, public_keys_json=trust)
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "STORED"
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "DUPLICATE"

    conflicting, conflicting_trust = signed_envelope(
        private_key, event_id="lifecycle-1", state="INVALIDATED"
    )
    conflicting_verified = verify_lifecycle_event(
        conflicting, public_keys_json=conflicting_trust
    )
    assert inbox.persist_verified(
        "gfx.liquidity.lifecycle.v1", conflicting, conflicting_verified
    ) == "CONFLICT"
    assert inbox.status() == {
        "signature_verified_events": 1,
        "source_attested_events": 0,
        "conflicts": 1,
        "quarantined_deliveries": 0,
    }


def test_quarantine_is_durable_and_counted(tmp_path) -> None:
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    inbox.persist_rejected("delivery-1", "bad-event", {"id": "bad-event"}, "signature_invalid")
    assert inbox.status()["quarantined_deliveries"] == 1
