from __future__ import annotations

import base64
import hashlib
import json
import os
import runpy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from psycopg import sql

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
    lifecycle_id: str | None = None,
    now: datetime | None = None,
) -> tuple[dict, str, str]:
    aggregate_id = lifecycle_id or event_id
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
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
            f"{aggregate_id}|{sequence}|{transition_state}|{occurred_at}".encode()
        ).hexdigest()
        transition_projection = {
            "lifecycle_id": aggregate_id,
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
            "lifecycle_id": aggregate_id,
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
            "correlation_id": aggregate_id,
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
        "specversion": "1.0",
        "id": transition_id,
        "type": "com.gavlix.market.liquidity.lifecycle.v1",
        "source": "urn:gavlix:service:9:fx-liquidity-analysis-service",
        "subject": "EURUSD/1m",
        "time": data["temporal"]["confirmed_at"],
        "datacontenttype": "application/json",
        "dataschema": "https://contracts.gavlix.com/schemas/liquidity-lifecycle-evidence/v1/event.schema.json",
        "data": data,
        "producer_id": "fx-liquidity-analysis-service",
        "correlation_id": aggregate_id,
        "causation_id": "sweep-1",
        "schema_id": "https://contracts.gavlix.com/schemas/liquidity-lifecycle-evidence/v1/event.schema.json",
        "schema_version": "liquidity-lifecycle-evidence/v1",
        "classification": "analytical",
        "sensitivity": "internal",
        "partition_key": "EURUSD",
        "idempotency_key": f"liquidity-lifecycle-transition:{transition_id}",
        "producer_service": "fx-liquidity-analysis-service",
        "source_timestamp": data["temporal"]["source_candle_at"],
        "sequence_number": 2,
        "quality_status": "PASS",
        "provenance": data["provenance"],
        "event_time": data["temporal"]["confirmed_at"],
        "publication_time": now.isoformat().replace("+00:00", "Z"),
        "broker_acceptance_time": None,
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


def test_rejects_tampered_cloud_event_routing_metadata() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    envelope["subject"] = "GBPUSD/1m"
    with pytest.raises(LifecycleEvidenceError, match="cloudevent_metadata_mismatch"):
        verify_lifecycle_event(
            envelope, public_keys_json=trust, source_public_keys_json=source_trust
        )


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


def test_inbox_rejects_unsigned_cloud_event_envelope_mutation(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "STORED"

    changed_envelope = {**envelope, "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    changed_verified = verify_lifecycle_event(
        changed_envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert changed_verified["payload_sha256"] == verified["payload_sha256"]
    assert (
        inbox.persist_verified("gfx.liquidity.lifecycle.v1", changed_envelope, changed_verified)
        == "CONFLICT"
    )
    assert inbox.status()["conflicts"] == 1


def test_quarantine_is_durable_and_delivery_id_collisions_are_audited(tmp_path) -> None:
    inbox = LifecycleEvidenceInbox(str(tmp_path / "lifecycle-inbox.sqlite3"))
    inbox.persist_rejected("delivery-1", "bad-event", {"id": "bad-event"}, "signature_invalid")
    inbox.persist_rejected("delivery-1", "other-event", {"id": "other-event"}, "different_payload")
    inbox.persist_rejected("delivery-1", "other-event", {"id": "other-event"}, "different_payload")
    status = inbox.status()
    assert status["quarantined_deliveries"] == 1
    assert status["conflicts"] == 1


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


def test_separately_verified_source_attestation_is_eligible_for_sqlite_replay(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    initially_unattested = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json="{}"
    )
    later_attested = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert initially_unattested["source_verified"] is False
    assert later_attested["source_verified"] is True

    inbox_path = str(tmp_path / "lifecycle-inbox.sqlite3")
    initial_inbox = LifecycleEvidenceInbox(
        inbox_path,
        public_keys_json=trust,
        source_public_keys_json="{}",
    )
    assert (
        initial_inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, initially_unattested)
        == "STORED"
    )
    assert initial_inbox.status()["pending_source_attestation_events"] == 1
    # A process restart with an updated source trust bundle promotes the
    # existing immutable event without requiring a broker redelivery.
    inbox = LifecycleEvidenceInbox(
        inbox_path,
        public_keys_json=trust,
        source_public_keys_json=source_trust,
    )
    manifest = inbox.point_in_time_evidence(
        instrument="EURUSD",
        timeframe="1m",
        source_dataset_id=later_attested["source_dataset_id"],
        price_basis="MID",
        cutoffs=[datetime.now(UTC) + timedelta(minutes=1)],
    )
    assert manifest[0]["evidence_count"] == 1
    assert manifest[0]["evidence"][0]["event_id"] == later_attested["event_id"]
    assert inbox.status()["pending_source_attestation_events"] == 0


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


def _sync_cloud_event_metadata(envelope: dict) -> None:
    data = envelope["data"]
    lifecycle = data["lifecycle"]
    temporal = data["temporal"]
    instrument = data["instrument"]
    envelope.update(
        {
            "id": data["event_id"],
            "subject": f"{instrument['canonical_id']}/{data['timeframe']}",
            "time": temporal["confirmed_at"],
            "correlation_id": lifecycle["lifecycle_id"],
            "causation_id": lifecycle["sweep_event_id"],
            "partition_key": instrument["canonical_id"],
            "idempotency_key": f"liquidity-lifecycle-transition:{data['event_id']}",
            "source_timestamp": temporal["source_candle_at"],
            "sequence_number": lifecycle["transition_sequence"],
            "quality_status": data["quality"]["quality_status"],
            "provenance": data["provenance"],
            "event_time": temporal["confirmed_at"],
        }
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
    _sync_cloud_event_metadata(earlier)
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
    _sync_cloud_event_metadata(earlier)
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
    initially_unattested = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json="{}"
    )
    assert initially_unattested["source_verified"] is False
    initial_inbox = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN,
        public_keys_json=trust,
        source_public_keys_json="{}",
        expected_topic=topic,
    )
    assert initial_inbox.persist_verified(topic, envelope, initially_unattested) == "STORED"
    assert initial_inbox.status()["pending_source_attestation_events"] == 1
    # The replay reader promotes the immutable event after the source key is
    # added to the trusted bundle; no broker redelivery is required.
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
    assert restarted.status()["pending_source_attestation_events"] == 0
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
def test_postgres_inbox_rejects_unsigned_cloud_event_envelope_mutation() -> None:
    private_key = Ed25519PrivateKey.generate()
    envelope, trust, source_trust = signed_envelope(private_key)
    verified = verify_lifecycle_event(
        envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    inbox = PostgresLifecycleEvidenceInbox(
        POSTGRES_DSN, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert inbox.persist_verified("gfx.liquidity.lifecycle.v1", envelope, verified) == "STORED"

    changed_envelope = {
        **envelope,
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }
    changed_verified = verify_lifecycle_event(
        changed_envelope, public_keys_json=trust, source_public_keys_json=source_trust
    )
    assert changed_verified["payload_sha256"] == verified["payload_sha256"]
    assert (
        inbox.persist_verified(
            "gfx.liquidity.lifecycle.v1", changed_envelope, changed_verified
        )
        == "CONFLICT"
    )
    assert inbox.status()["conflicts"] == 1


def test_postgres_inbox_serializes_concurrent_history_forks() -> None:
    lifecycle_id = f"postgres-fork-{uuid.uuid4()}"
    key_a, key_b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    common_time = datetime.now(UTC).replace(microsecond=0)
    env_a, trust_a, source_a = signed_envelope(
        key_a,
        event_id="postgres-fork-branch-a",
        lifecycle_id=lifecycle_id,
        state="DISPLACEMENT_CONFIRMED",
        now=common_time,
    )
    env_b, trust_b, source_b = signed_envelope(
        key_b,
        event_id="postgres-fork-branch-b",
        lifecycle_id=lifecycle_id,
        state="INVALIDATED",
        now=common_time,
    )
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
    with pytest.raises(psycopg.Error, match="append-only"):
        with psycopg.connect(POSTGRES_DSN) as db:
            db.execute(
                "UPDATE lifecycle_evidence_source_verifications "
                "SET source_dataset_id='tampered' WHERE event_id=%s",
                (verified["event_id"],),
            )
    delivery_id = f"rejected-{uuid.uuid4()}"
    inbox.persist_rejected(delivery_id, None, {"invalid": True}, "signature_invalid")
    inbox.persist_rejected(delivery_id, None, {"invalid": False}, "duplicate_delivery")
    status = inbox.status()
    assert status["quarantined_deliveries"] >= 1
    assert status["conflicts"] >= 2


@pytest.mark.skipif(
    not POSTGRES_DSN, reason="TEST_POSTGRES_URL is required for PostgreSQL migration tests"
)
def test_sqlite_inbox_cutover_preserves_evidence_conflicts_and_quarantine(tmp_path) -> None:
    private_key_a = Ed25519PrivateKey.generate()
    private_key_b = Ed25519PrivateKey.generate()
    lifecycle_id = f"migration-lifecycle-{uuid.uuid4()}"
    common_time = datetime.now(UTC).replace(microsecond=0)
    envelope_a, trust_a, source_trust_a = signed_envelope(
        private_key_a,
        event_id="migration-branch-a",
        lifecycle_id=lifecycle_id,
        state="DISPLACEMENT_CONFIRMED",
        now=common_time,
    )
    envelope_b, trust_b, source_trust_b = signed_envelope(
        private_key_b,
        event_id="migration-branch-b",
        lifecycle_id=lifecycle_id,
        state="INVALIDATED",
        now=common_time,
    )
    verified_a = verify_lifecycle_event(
        envelope_a, public_keys_json=trust_a, source_public_keys_json=source_trust_a
    )
    verified_b = verify_lifecycle_event(
        envelope_b, public_keys_json=trust_b, source_public_keys_json=source_trust_b
    )
    sqlite_path = tmp_path / "lifecycle-inbox.sqlite3"
    source = LifecycleEvidenceInbox(
        str(sqlite_path),
        public_keys_json=trust_a,
        source_public_keys_json=source_trust_a,
    )
    assert source.persist_verified("gfx.liquidity.lifecycle.v1", envelope_a, verified_a) == "STORED"
    assert (
        source.persist_verified("gfx.liquidity.lifecycle.v1", envelope_b, verified_b) == "CONFLICT"
    )
    source.persist_rejected(
        "migration-delivery-1", verified_b["event_id"], envelope_b, "invalid_for_replay"
    )
    source.persist_rejected(
        "migration-delivery-1", verified_b["event_id"], envelope_a, "conflicting_quarantine_payload"
    )
    with source._connect() as source_db:
        source_conflict_ids = [
            row["conflict_id"]
            for row in source_db.execute(
                "SELECT conflict_id FROM lifecycle_evidence_conflicts ORDER BY conflict_id"
            )
        ]

    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrate_lifecycle_inbox_sqlite_to_postgres.py"
    )
    schema_name = f"migration_test_{uuid.uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    dsn_parts = urlsplit(POSTGRES_DSN)
    dsn_query = dict(parse_qsl(dsn_parts.query, keep_blank_values=True))
    dsn_query["options"] = f"-csearch_path={schema_name}"
    isolated_dsn = urlunsplit(
        (
            dsn_parts.scheme,
            dsn_parts.netloc,
            dsn_parts.path,
            urlencode(dsn_query),
            dsn_parts.fragment,
        )
    )
    try:
        pre_migration = PostgresLifecycleEvidenceInbox(
            isolated_dsn,
            public_keys_json=trust_a,
            source_public_keys_json=source_trust_a,
        )
        pre_migration.assert_sqlite_cutover_complete(
            str(tmp_path / "new-install-without-legacy.sqlite3")
        )
        with pytest.raises(RuntimeError, match="not fully imported"):
            pre_migration.assert_sqlite_cutover_complete(str(sqlite_path))

        migration_module = runpy.run_path(str(script))
        migrate = migration_module["migrate"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: migrate(sqlite_path, isolated_dsn),
                    range(2),
                )
            )
        assert sorted(result["status"] for result in results) == [
            "already_imported",
            "imported",
        ]

        migrated = PostgresLifecycleEvidenceInbox(
            isolated_dsn,
            public_keys_json=trust_a,
            source_public_keys_json=source_trust_a,
        )
        migrated.assert_sqlite_cutover_complete(str(sqlite_path))
        status = migrated.status()
        assert status["source_attested_events"] >= 1
        assert status["conflicts"] >= 2
        assert status["quarantined_deliveries"] >= 1
        with migrated._connect() as migrated_db:
            migrated_conflict_ids = [
                row["conflict_id"]
                for row in migrated_db.execute(
                    "SELECT conflict_id FROM lifecycle_evidence_conflicts ORDER BY conflict_id"
                )
            ]
        assert migrated_conflict_ids == source_conflict_ids
        history = migrated.lifecycle_history(verified_a["lifecycle_id"])
        assert history is not None
        assert history["head_sequence"] == verified_a["transition_sequence"]
        manifests = migrated.point_in_time_evidence(
            instrument=verified_a["instrument"],
            timeframe=verified_a["timeframe"],
            source_dataset_id=verified_a["source_dataset_id"],
            price_basis="MID",
            cutoffs=[datetime.now(UTC) + timedelta(minutes=1)],
        )
        assert manifests[0]["evidence_count"] == 1
        assert manifests[0]["evidence"][0]["event_id"] == verified_a["event_id"]

        extra_envelope, extra_trust, extra_source_trust = signed_envelope(
            private_key_a, event_id=f"migration-extra-{uuid.uuid4()}"
        )
        extra_verified = verify_lifecycle_event(
            extra_envelope,
            public_keys_json=extra_trust,
            source_public_keys_json=extra_source_trust,
        )
        assert (
            source.persist_verified("gfx.liquidity.lifecycle.v1", extra_envelope, extra_verified)
            == "STORED"
        )
        with pytest.raises(RuntimeError, match="not fully imported"):
            migrated.assert_sqlite_cutover_complete(str(sqlite_path))
    finally:
        with psycopg.connect(POSTGRES_DSN) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
