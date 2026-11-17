from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.app.clients.lifecycle_evidence import (
    LifecycleEvidenceError,
    LifecycleEvidenceInbox,
    PostgresLifecycleEvidenceInbox,
    verify_lifecycle_event,
)


def signed_envelope(
    private_key: Ed25519PrivateKey,
    *,
    event_id: str = "lifecycle-1",
    state: str = "DISPLACEMENT_CONFIRMED",
    reverse_temporal_order: bool = False,
) -> tuple[dict, str, str]:
    now = datetime.now(UTC).replace(microsecond=0)
    source_at = now - timedelta(minutes=4)
    observed_at = now - timedelta(minutes=2)
    confirmed_at = now - timedelta(minutes=2)
    if reverse_temporal_order:
        source_at = now
        observed_at = now - timedelta(minutes=2)
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "service9-ed25519-test"
    service1_private_key = Ed25519PrivateKey.generate()
    service1_public_raw = service1_private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    service1_key_id = "service1-historical-test"
    source_dataset_sha256 = "b" * 64
    source_dataset_id = f"historical:test-provider:{source_dataset_sha256[:24]}"
    source_attestation = {
        "version": "1",
        "purpose": "indicator-candle-dataset",
        "algorithm": "Ed25519",
        "provider_id": "test-provider",
        "source_id": source_dataset_id,
        "key_id": service1_key_id,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "instrument": "EURUSD",
        "timeframe": "1M",
        "dataset_sha256": source_dataset_sha256,
        "quality": {
            "is_final": True,
            "valid": True,
            "coverage_complete": True,
            "rejected_count": 0,
            "duplicate_count": 0,
            "candle_count": 10,
        },
        "volume_semantics": "not_supplied",
        "source_metadata": {
            "provider_id": "test-provider",
            "service1_timeframe": "M1",
            "indicator_timeframe": "1M",
            "price_basis": "midpoint",
            "retrieved_at": now.isoformat().replace("+00:00", "Z"),
            "coverage": {},
            "validation_summary": {},
            "candle_sources": [],
            "volume_kinds": [],
            "limitations": [],
        },
    }
    source_attestation["signature"] = "ed25519=" + base64.b64encode(
        service1_private_key.sign(
            json.dumps(
                source_attestation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        )
    ).decode("ascii")
    sweep_occurred_at = source_at.isoformat().replace("+00:00", "Z")
    displacement_occurred_at = observed_at.isoformat().replace("+00:00", "Z")
    transition_history = []
    previous_transition_hash = "0" * 64
    for sequence, transition_state, occurred_at in (
        (1, "SWEEP_CONFIRMED", sweep_occurred_at),
        (2, state, displacement_occurred_at),
    ):
        transition_id = hashlib.sha256(
            f"{event_id}|{sequence}|{transition_state}|{occurred_at}".encode()
        ).hexdigest()
        transition_projection = {
            "lifecycle_id": event_id,
            "transition_id": transition_id,
            "sequence": sequence,
            "state": transition_state,
            "occurred_at": occurred_at,
            "previous_transition_sha256": previous_transition_hash,
        }
        transition_hash = hashlib.sha256(rfc8785.dumps(transition_projection)).hexdigest()
        transition_history.append({**transition_projection, "transition_sha256": transition_hash})
        previous_transition_hash = transition_hash
    transition_id = transition_history[-1]["transition_id"]
    transition_hash = transition_history[-1]["transition_sha256"]
    data = {
        "contract_version": "liquidity-lifecycle-evidence/v1",
        "event_id": transition_id,
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
            "transition_id": transition_id,
            "transition_sequence": 2,
            "transition_sha256": transition_hash,
            "previous_transition_sha256": transition_history[-1]["previous_transition_sha256"],
            "transition_history": transition_history,
            "sweep_event_id": "sweep-1",
            "state": state,
            "direction": "BEARISH",
            "anchor_price": "1.1",
            "algorithm": "causal-post-sweep-lifecycle",
            "algorithm_version": "1.0.0",
            "classification_reasons": ["observed close confirmed displacement"],
            "sweep_confirmation_time": sweep_occurred_at,
            "displacement_confirmed_at": (
                None if state == "INVALIDATED" else observed_at.isoformat().replace("+00:00", "Z")
            ),
            "midpoint_first_reached_at": None,
            "consolidation_candidate_at": None,
            "invalidated_at": displacement_occurred_at if state == "INVALIDATED" else None,
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
            "price_basis": "MID",
            "source_id": source_dataset_id,
            "source_timezone": "UTC",
        },
        "quality": {
            "evidence_class": "DERIVED",
            "quality_status": "PASS",
            "source_attestation_status": "SERVICE1_DATASET_SIGNATURE_VERIFIED",
            "freshness_status": "FRESH",
            "uncertainty_status": "UNQUANTIFIED",
            "limitations": ["source market data is not independently attested"],
        },
        "provenance": {
            "source_event_id": "sweep-1",
            "source_payload_sha256": "a" * 64,
            "source_dataset_id": source_dataset_id,
            "source_dataset_instrument": "EURUSD",
            "source_dataset_sha256": source_dataset_sha256,
            "source_provider_id": "test-provider",
            "source_attestation": source_attestation,
            "lineage": [
                {
                    "service_id": "fx-liquidity-analysis-service",
                    "artifact_id": "causal-post-sweep-lifecycle",
                    "artifact_version": "1.0.0",
                }
            ],
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
        "signature": base64.b64encode(private_key.sign(bytes.fromhex(digest))).decode("ascii"),
        "signed_at": now.isoformat().replace("+00:00", "Z"),
    }
    envelope = {
        "id": transition_id,
        "type": "com.gavlix.market.liquidity.lifecycle.v1",
        "producer_id": "fx-liquidity-analysis-service",
        "schema_version": "liquidity-lifecycle-evidence/v1",
        "schema_id": "https://contracts.gavlix.com/schemas/liquidity-lifecycle-evidence/v1/event.schema.json",
        "dataschema": "https://contracts.gavlix.com/schemas/liquidity-lifecycle-evidence/v1/event.schema.json",
        "data": data,
    }
    trust = json.dumps({key_id: base64.b64encode(public_raw).decode("ascii")})
    source_trust = json.dumps(
        {service1_key_id: base64.b64encode(service1_public_raw).decode("ascii")}
    )
    return envelope, trust, source_trust


def test_verifies_service9_ed25519_signature_and_temporal_contract() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    result = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert result["signature_verified"] is True
    assert result["source_verified"] is True
    assert result["instrument"] == "EURUSD"
    assert result["timeframe"] == "1m"


def test_rejects_payload_tampering_after_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    envelope["data"]["lifecycle"]["state"] = "INVALIDATED"
    with pytest.raises(LifecycleEvidenceError, match="payload_digest_mismatch"):
        verify_lifecycle_event(
            envelope, public_keys_json=trust, source_public_keys_json=source_trust
        )


def test_rejects_unknown_signing_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    envelope["data"]["integrity"]["key_id"] = "untrusted-key"
    with pytest.raises(LifecycleEvidenceError, match="signing_key_untrusted"):
        verify_lifecycle_event(
            envelope, public_keys_json=trust, source_public_keys_json=source_trust
        )


def test_rejects_non_monotonic_event_timestamps_even_with_valid_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key, reverse_temporal_order=True)
    with pytest.raises(
        LifecycleEvidenceError, match="temporal_order_invalid|transition_history_time_regression"
    ):
        verify_lifecycle_event(
            envelope, public_keys_json=trust, source_public_keys_json=source_trust
        )


def test_durable_inbox_deduplicates_and_records_event_id_conflicts(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "STORED"
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "DUPLICATE"

    conflicting, conflicting_trust, conflicting_source_trust = signed_envelope(
        private_key, event_id="lifecycle-1", state="INVALIDATED"
    )
    conflicting_verified = verify_lifecycle_event(
        conflicting,
        public_keys_json=conflicting_trust,
        source_public_keys_json=conflicting_source_trust,
    )
    assert (
        inbox.persist_verified("gfx.liquidity.lifecycle.v1", conflicting, conflicting_verified)
        == "CONFLICT"
    )
    status = inbox.status()
    assert status["signature_verified_events"] == 1
    assert status["source_attested_events"] == 1
    assert status["conflicts"] == 1
    assert status["quarantined_deliveries"] == 0
    assert status["unique_lifecycle_aggregates"] == 1
    assert status["highest_transition_sequence"] == 2


def test_quarantine_is_durable_and_counted(tmp_path) -> None:
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    inbox.persist_rejected("delivery-1", "bad-event", {"id": "bad-event"}, "signature_invalid")
    assert inbox.status()["quarantined_deliveries"] == 1


def test_point_in_time_inbox_context_excludes_events_until_available_at(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)
    now = datetime.now(UTC)
    contexts = inbox.point_in_time_contexts(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified["source_dataset_id"],
        price_basis="MID",
        cutoffs=[now - timedelta(minutes=1), now + timedelta(minutes=1)],
    )
    assert contexts[0] is None
    assert contexts[1] is not None
    assert contexts[1]["liquidity_sweep_bearish"] == 1.0
    assert contexts[1]["liquidity_displacement_confirmed"] == 1.0


def test_rejects_invalid_service1_signature_even_when_service9_event_signature_is_valid() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    signature = envelope["data"]["provenance"]["source_attestation"]["signature"]
    envelope["data"]["provenance"]["source_attestation"]["signature"] = signature[:-2] + (
        "AA" if signature[-2:] != "AA" else "BB"
    )
    data = envelope["data"]
    integrity = data.pop("integrity")
    digest = hashlib.sha256(rfc8785.dumps(data)).hexdigest()
    data["integrity"] = {
        **integrity,
        "payload_sha256": digest,
        "signature": base64.b64encode(private_key.sign(bytes.fromhex(digest))).decode("ascii"),
    }
    with pytest.raises(LifecycleEvidenceError, match="source_attestation_signature_invalid"):
        verify_lifecycle_event(
            envelope,
            public_keys_json=trust,
            source_public_keys_json=source_trust,
        )


def test_point_in_time_contexts_use_utc_instants_and_preserve_unsorted_cutoff_order(
    tmp_path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)

    # Producer availability uses a trailing Z; consumer receipt is persisted
    # as +00:00. Cutoff equality is tested without mutating immutable inbox data.
    with inbox._connect() as connection:
        received_value = connection.execute(
            "SELECT received_at FROM lifecycle_evidence_inbox WHERE event_id=?",
            (verified["event_id"],),
        ).fetchone()["received_at"]
    receipt_at = datetime.fromisoformat(received_value)
    equivalent_z_instant = datetime.fromisoformat(receipt_at.isoformat().replace("+00:00", "Z"))

    contexts = inbox.point_in_time_contexts(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified["source_dataset_id"],
        price_basis="MID",
        # Deliberately reverse chronological order; output must match this order.
        cutoffs=[equivalent_z_instant, equivalent_z_instant - timedelta(microseconds=1)],
    )
    assert contexts[0] is not None
    assert contexts[0]["liquidity_sweep_bearish"] == 1.0
    assert contexts[1] is None


def test_point_in_time_contexts_reject_naive_cutoffs(tmp_path) -> None:
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    with pytest.raises(ValueError, match="timezone-aware"):
        inbox.point_in_time_contexts(
            instrument="EURUSD",
            timeframe="1m",
            source_dataset_id="historical:test-provider:abc",
            price_basis="MID",
            cutoffs=[datetime(2026, 1, 1)],
        )


def _resign_service9_event(envelope: dict, private_key: Ed25519PrivateKey) -> None:
    data = envelope["data"]
    integrity = data.pop("integrity")
    digest = hashlib.sha256(rfc8785.dumps(data)).hexdigest()
    data["integrity"] = {
        **integrity,
        "payload_sha256": digest,
        "signature": base64.b64encode(private_key.sign(bytes.fromhex(digest))).decode("ascii"),
    }


def test_rejects_a_forked_or_tampered_transition_hash_chain() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    envelope["data"]["lifecycle"]["transition_history"][0]["state"] = "INVALIDATED"
    _resign_service9_event(envelope, private_key)
    with pytest.raises(
        LifecycleEvidenceError,
        match="transition_identity_invalid|transition_hash_chain_invalid|transition_history_order_invalid",
    ):
        verify_lifecycle_event(
            envelope, public_keys_json=trust, source_public_keys_json=source_trust
        )


def test_late_lower_sequence_transition_cannot_roll_back_replay_state(tmp_path) -> None:
    import copy

    private_key = Ed25519PrivateKey.generate()
    later, trust, source_trust = signed_envelope(private_key, state="DISPLACEMENT_CONFIRMED")
    earlier = copy.deepcopy(later)
    first = earlier["data"]["lifecycle"]["transition_history"][0]
    data = earlier["data"]
    lifecycle = data["lifecycle"]
    data["event_id"] = first["transition_id"]
    lifecycle["transition_id"] = first["transition_id"]
    lifecycle["transition_sequence"] = 1
    lifecycle["transition_sha256"] = first["transition_sha256"]
    lifecycle["previous_transition_sha256"] = first["previous_transition_sha256"]
    lifecycle["transition_history"] = [first]
    lifecycle["state"] = "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT"
    lifecycle["displacement_confirmed_at"] = None
    data["temporal"]["observed_at"] = first["occurred_at"]
    data["temporal"]["confirmed_at"] = first["occurred_at"]
    earlier["id"] = first["transition_id"]
    _resign_service9_event(earlier, private_key)

    verified_later = verify_lifecycle_event(
        later, public_keys_json=trust, source_public_keys_json=source_trust
    )
    verified_earlier = verify_lifecycle_event(
        earlier, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", later, verified_later) == "STORED"
    assert (
        inbox.persist_verified("gfx.liquidity.lifecycle.v1", earlier, verified_earlier) == "STORED"
    )

    contexts = inbox.point_in_time_contexts(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified_later["source_dataset_id"],
        price_basis="MID",
        cutoffs=[datetime.now(UTC) + timedelta(minutes=1)],
    )
    assert contexts[0] is not None
    assert contexts[0]["liquidity_displacement_confirmed"] == 1.0


def test_prediction_origin_manifest_identifies_exact_evidence(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)
    origin = datetime.now(UTC) + timedelta(minutes=1)
    manifest = inbox.point_in_time_evidence(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified["source_dataset_id"],
        price_basis="MID",
        cutoffs=[origin],
    )[0]
    assert manifest["evidence_count"] == 1
    assert manifest["evidence"][0]["event_id"] == verified["event_id"]
    assert len(manifest["evidence_set_sha256"]) == 64
    assert manifest["evidence"][0]["consumer_received_at"] <= origin.isoformat()


def test_replay_reverifies_persisted_signed_bytes_and_fails_closed_on_database_tampering(
    tmp_path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)
    with inbox._connect() as connection:
        # Simulate an offline administrator/attacker modifying the SQLite file
        # outside the application's append-only trigger protections.
        connection.execute("DROP TRIGGER trg_lifecycle_inbox_no_update")
        connection.execute(
            "UPDATE lifecycle_evidence_inbox SET envelope_json=json_set(envelope_json, '$.data.lifecycle.direction', 'BULLISH') WHERE event_id=?",
            (verified["event_id"],),
        )
    with pytest.raises(LifecycleEvidenceError):
        inbox.point_in_time_contexts(
            instrument="EURUSD",
            timeframe="1m",
            source_dataset_id=verified["source_dataset_id"],
            price_basis="MID",
            cutoffs=[datetime.now(UTC) + timedelta(minutes=1)],
        )


def test_durable_inbox_reconstructs_signed_lifecycle_history(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)
    history = inbox.lifecycle_history(verified["lifecycle_id"])
    assert history is not None
    assert history["head_event_id"] == verified["event_id"]
    assert history["head_sequence"] == 2
    assert [item["sequence"] for item in history["reconstructed_transition_history"]] == [1, 2]
    assert history["signature_reverified"] is True


def test_inbox_rejects_divergent_history_prefix_even_when_each_event_is_signed(tmp_path) -> None:
    import copy

    private_key = Ed25519PrivateKey.generate()
    later, trust, source_trust = signed_envelope(private_key)
    earlier = copy.deepcopy(later)
    first = earlier["data"]["lifecycle"]["transition_history"][0]
    earlier["data"]["event_id"] = first["transition_id"]
    earlier_lifecycle = earlier["data"]["lifecycle"]
    earlier_lifecycle["transition_id"] = first["transition_id"]
    earlier_lifecycle["transition_sequence"] = 1
    earlier_lifecycle["transition_sha256"] = first["transition_sha256"]
    earlier_lifecycle["previous_transition_sha256"] = first["previous_transition_sha256"]
    earlier_lifecycle["transition_history"] = [first]
    earlier_lifecycle["state"] = "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT"
    earlier_lifecycle["displacement_confirmed_at"] = None
    earlier["data"]["temporal"]["observed_at"] = first["occurred_at"]
    earlier["data"]["temporal"]["confirmed_at"] = first["occurred_at"]
    earlier["id"] = first["transition_id"]
    _resign_service9_event(earlier, private_key)

    divergent = copy.deepcopy(later)
    data = divergent["data"]
    lifecycle = data["lifecycle"]
    history = lifecycle["transition_history"]
    first_item = history[0]
    changed_time = (
        (
            datetime.fromisoformat(first_item["occurred_at"].replace("Z", "+00:00"))
            + timedelta(seconds=1)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    first_item["occurred_at"] = changed_time
    first_item["transition_id"] = hashlib.sha256(
        f"{lifecycle['lifecycle_id']}|1|{first_item['state']}|{changed_time}".encode()
    ).hexdigest()
    first_projection = {
        key: first_item[key]
        for key in (
            "lifecycle_id",
            "transition_id",
            "sequence",
            "state",
            "occurred_at",
            "previous_transition_sha256",
        )
    }
    first_item["transition_sha256"] = hashlib.sha256(rfc8785.dumps(first_projection)).hexdigest()
    second_item = history[1]
    second_item["previous_transition_sha256"] = first_item["transition_sha256"]
    second_projection = {
        key: second_item[key]
        for key in (
            "lifecycle_id",
            "transition_id",
            "sequence",
            "state",
            "occurred_at",
            "previous_transition_sha256",
        )
    }
    second_item["transition_sha256"] = hashlib.sha256(rfc8785.dumps(second_projection)).hexdigest()
    lifecycle["sweep_confirmation_time"] = changed_time
    lifecycle["previous_transition_sha256"] = second_item["previous_transition_sha256"]
    lifecycle["transition_sha256"] = second_item["transition_sha256"]
    _resign_service9_event(divergent, private_key)

    verified_earlier = verify_lifecycle_event(
        earlier, public_keys_json=trust, source_public_keys_json=source_trust
    )
    verified_divergent = verify_lifecycle_event(
        divergent, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    assert (
        inbox.persist_verified("gfx.liquidity.lifecycle.v1", earlier, verified_earlier) == "STORED"
    )
    assert (
        inbox.persist_verified("gfx.liquidity.lifecycle.v1", divergent, verified_divergent)
        == "CONFLICT"
    )
    assert inbox.status()["conflicts"] == 1


def test_replay_rejects_tampered_consumer_receipt_epoch(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(
        str(tmp_path / "lifecycle-inbox.sqlite3"),
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified)
    with inbox._connect() as connection:
        connection.execute("DROP TRIGGER trg_lifecycle_inbox_no_update")
        connection.execute(
            "UPDATE lifecycle_evidence_inbox SET received_at_epoch_us=0 WHERE event_id=?",
            (verified["event_id"],),
        )
    with pytest.raises(LifecycleEvidenceError, match="persisted_evidence_integrity_mismatch"):
        inbox.point_in_time_contexts(
            instrument="EURUSD",
            timeframe="1m",
            source_dataset_id=verified["source_dataset_id"],
            price_basis="MID",
            cutoffs=[datetime.now(UTC) + timedelta(minutes=1)],
        )


POSTGRES_DSN = os.getenv("TEST_POSTGRES_URL", "").strip()


@pytest.mark.skipif(
    not POSTGRES_DSN, reason="TEST_POSTGRES_URL is required for PostgreSQL integration tests"
)
def test_postgres_inbox_restart_history_and_point_in_time_evidence() -> None:
    private_key = Ed25519PrivateKey.generate()
    lifecycle_id = f"postgres-lifecycle-{uuid.uuid4()}"
    envelope, trust, source_trust = signed_envelope(private_key, event_id=lifecycle_id)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    topic = "gfx.liquidity.lifecycle.v1"
    inbox = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN,
        public_keys_json=trust,
        source_public_keys_json=source_trust,
        expected_topic=topic,
    )
    assert inbox.persist_verified(topic, envelope, verified) == "STORED"
    restarted = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN,
        public_keys_json=trust,
        source_public_keys_json=source_trust,
        expected_topic=topic,
    )
    assert restarted.persist_verified(topic, envelope, verified) == "DUPLICATE"

    before_receipt = datetime.now(UTC) - timedelta(seconds=1)
    after_receipt = datetime.now(UTC) + timedelta(minutes=1)
    manifests = restarted.point_in_time_evidence(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified["source_dataset_id"],
        price_basis="MID",
        cutoffs=[before_receipt, after_receipt],
    )
    assert manifests[0]["evidence_count"] == 0
    assert manifests[1]["evidence_count"] == 1
    assert manifests[1]["evidence"][0]["event_id"] == verified["event_id"]
    contexts = restarted.point_in_time_contexts(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=verified["source_dataset_id"],
        price_basis="MID",
        cutoffs=[after_receipt],
    )
    assert contexts[0] is not None
    history = restarted.lifecycle_history(lifecycle_id)
    assert history is not None
    assert history["head_event_id"] == verified["event_id"]
    assert history["signature_reverified"] is True


@pytest.mark.skipif(
    not POSTGRES_DSN, reason="TEST_POSTGRES_URL is required for PostgreSQL integration tests"
)
def test_postgres_inbox_serializes_concurrent_history_forks() -> None:
    lifecycle_id = f"postgres-fork-{uuid.uuid4()}"
    key_a, key_b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    env_a, trust_a, source_a = signed_envelope(
        key_a, event_id=lifecycle_id, state="DISPLACEMENT_CONFIRMED"
    )
    env_b, trust_b, source_b = signed_envelope(key_b, event_id=lifecycle_id, state="INVALIDATED")
    verified_a = verify_lifecycle_event(
        env_a, public_keys_json=trust_a, source_public_keys_json=source_a
    )
    verified_b = verify_lifecycle_event(
        env_b, public_keys_json=trust_b, source_public_keys_json=source_b
    )
    merged_trust = {**json.loads(trust_a), **json.loads(trust_b)}
    merged_source = {**json.loads(source_a), **json.loads(source_b)}
    inbox_a = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN,
        public_keys_json=json.dumps(merged_trust),
        source_public_keys_json=json.dumps(merged_source),
    )
    inbox_b = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN,
        public_keys_json=json.dumps(merged_trust),
        source_public_keys_json=json.dumps(merged_source),
    )
    args = (
        ("gfx.liquidity.lifecycle.v1", env_a, verified_a),
        ("gfx.liquidity.lifecycle.v1", env_b, verified_b),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: (
                    inbox_a if item[1]["data"]["event_id"] == verified_a["event_id"] else inbox_b
                ).persist_verified(*item),
                args,
            )
        )
    assert sorted(results) == ["CONFLICT", "STORED"]
    assert inbox_a.status()["conflicts"] >= 1


@pytest.mark.skipif(
    not POSTGRES_DSN, reason="TEST_POSTGRES_URL is required for PostgreSQL integration tests"
)
def test_postgres_inbox_evidence_and_quarantine_are_append_only() -> None:
    private_key = Ed25519PrivateKey.generate()
    lifecycle_id = f"postgres-immutable-{uuid.uuid4()}"
    envelope, trust, source_trust = signed_envelope(private_key, event_id=lifecycle_id)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "STORED"
    with pytest.raises(psycopg.Error, match="append-only"):
        with psycopg.connect(POSTGRES_DSN) as db:
            db.execute(
                "UPDATE lifecycle_evidence_inbox SET envelope_json='{}' WHERE event_id=%s",
                (verified["event_id"],),
            )
    delivery_id = f"rejected-{uuid.uuid4()}"
    inbox.persist_rejected(delivery_id, None, {"invalid": True}, "signature_invalid")
    inbox.persist_rejected(delivery_id, None, {"invalid": False}, "duplicate_delivery")
    assert inbox.status()["quarantined_deliveries"] >= 1
