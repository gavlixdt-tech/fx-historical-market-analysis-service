"""Service 62 lifecycle evidence consumer, verifier and durable Service 2 inbox."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from backend.app.core.config import Settings

logger = logging.getLogger(__name__)
EXPECTED_PRODUCER = "fx-liquidity-analysis-service"
EXPECTED_EVENT_TYPE = "com.gavlix.market.liquidity.lifecycle.v1"
EXPECTED_SCHEMA = "liquidity-lifecycle-evidence/v1"
EXPECTED_SCHEMA_ID = (
    "https://contracts.gavlix.com/schemas/liquidity-lifecycle-evidence/v1/event.schema.json"
)


class LifecycleEvidenceError(ValueError):
    """Raised when a lifecycle event fails the signed evidence contract."""


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _service1_canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _verify_service1_source_attestation(data: dict[str, Any], source_public_keys_json: str) -> bool:
    provenance = data.get("provenance")
    instrument = data.get("instrument")
    market_basis = data.get("market_basis")
    quality = data.get("quality")
    if not all(isinstance(item, dict) for item in (provenance, instrument, market_basis, quality)):
        raise LifecycleEvidenceError("source_attestation_context_invalid")
    attestation = provenance.get("source_attestation")
    expected_fields = {
        "version",
        "purpose",
        "algorithm",
        "provider_id",
        "source_id",
        "key_id",
        "issued_at",
        "observed_at",
        "instrument",
        "timeframe",
        "dataset_sha256",
        "quality",
        "volume_semantics",
        "source_metadata",
        "signature",
    }
    if not isinstance(attestation, dict) or set(attestation) != expected_fields:
        raise LifecycleEvidenceError("source_attestation_missing_or_invalid")
    metadata = attestation.get("source_metadata")
    attestation_quality = attestation.get("quality")
    expected_metadata_fields = {
        "provider_id",
        "service1_timeframe",
        "indicator_timeframe",
        "price_basis",
        "retrieved_at",
        "coverage",
        "validation_summary",
        "candle_sources",
        "volume_kinds",
        "limitations",
    }
    expected_quality_fields = {
        "is_final",
        "valid",
        "coverage_complete",
        "rejected_count",
        "duplicate_count",
        "candle_count",
    }
    timeframe_map = {
        "1m": ("M1", "1M"),
        "5m": ("M5", "5M"),
        "15m": ("M15", "15M"),
        "30m": ("M30", "30M"),
        "1h": ("H1", "1H"),
        "4h": ("H4", "4H"),
        "1d": ("D1", "1D"),
    }
    if (
        attestation.get("version") != "1"
        or attestation.get("purpose") != "indicator-candle-dataset"
        or attestation.get("algorithm") != "Ed25519"
        or attestation.get("instrument") != provenance.get("source_dataset_instrument")
        or not isinstance(provenance.get("source_dataset_instrument"), str)
        or "".join(
            char for char in provenance["source_dataset_instrument"] if char.isalpha()
        ).upper()
        != instrument.get("canonical_id")
        or attestation.get("timeframe")
        != (timeframe_map.get(data.get("timeframe")) or (None, None))[1]
        or attestation.get("source_id") != provenance.get("source_dataset_id")
        or attestation.get("dataset_sha256") != provenance.get("source_dataset_sha256")
        or attestation.get("provider_id") != provenance.get("source_provider_id")
        or attestation.get("source_id") != market_basis.get("source_id")
        or not isinstance(metadata, dict)
        or set(metadata) != expected_metadata_fields
        or not isinstance(attestation_quality, dict)
        or set(attestation_quality) != expected_quality_fields
        or metadata.get("provider_id") != attestation.get("provider_id")
        or metadata.get("service1_timeframe")
        != (timeframe_map.get(data.get("timeframe")) or (None, None))[0]
        or metadata.get("indicator_timeframe") != attestation.get("timeframe")
        or metadata.get("retrieved_at") != attestation.get("observed_at")
        or attestation_quality.get("is_final") is not True
        or attestation_quality.get("valid") is not True
        or attestation_quality.get("coverage_complete") is not True
        or type(attestation_quality.get("rejected_count")) is not int
        or attestation_quality.get("rejected_count") != 0
        or type(attestation_quality.get("duplicate_count")) is not int
        or attestation_quality.get("duplicate_count") != 0
        or quality.get("quality_status") != "PASS"
        or quality.get("source_attestation_status") != "SERVICE1_DATASET_SIGNATURE_VERIFIED"
    ):
        raise LifecycleEvidenceError("source_attestation_metadata_mismatch")
    basis = str(metadata.get("price_basis", "vendor_defined")).lower()
    basis_map = {
        "bid": "BID",
        "ask": "ASK",
        "mid": "MID",
        "midpoint": "MID",
        "last": "LAST",
        "close": "LAST",
    }
    if market_basis.get("price_basis") != basis_map.get(basis, "VENDOR_DEFINED"):
        raise LifecycleEvidenceError("source_attestation_price_basis_mismatch")
    try:
        keys = json.loads(source_public_keys_json)
    except json.JSONDecodeError as exc:
        raise LifecycleEvidenceError("source_attestation_trust_bundle_invalid") from exc
    key_id = attestation.get("key_id")
    encoded_key = keys.get(key_id) if isinstance(keys, dict) and isinstance(key_id, str) else None
    if not isinstance(encoded_key, str):
        raise LifecycleEvidenceError("source_attestation_key_untrusted")
    signature_value = attestation.get("signature")
    if not isinstance(signature_value, str) or not signature_value.startswith("ed25519="):
        raise LifecycleEvidenceError("source_attestation_signature_malformed")
    try:
        public_key_bytes = base64.b64decode(encoded_key, validate=True)
        signature = base64.b64decode(signature_value[len("ed25519=") :], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        signed_projection = {key: value for key, value in attestation.items() if key != "signature"}
        public_key.verify(signature, _service1_canonical_json(signed_projection))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise LifecycleEvidenceError("source_attestation_signature_invalid") from exc
    return True


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise LifecycleEvidenceError(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleEvidenceError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LifecycleEvidenceError(f"{field}_timezone_missing")
    return parsed.astimezone(UTC)


def _epoch_microseconds(value: datetime) -> int:
    """Convert an aware datetime to an exact integer UTC epoch-microsecond value."""
    normalized = value.astimezone(UTC)
    delta = normalized - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def verify_lifecycle_event(
    envelope: dict[str, Any],
    *,
    public_keys_json: str,
    clock_skew_seconds: int = 60,
    source_public_keys_json: str = "{}",
) -> dict[str, Any]:
    """Verify the producer signature, identity, contract and monotonic timestamps."""
    if envelope.get("type") != EXPECTED_EVENT_TYPE:
        raise LifecycleEvidenceError("event_type_mismatch")
    if envelope.get("schema_version") != EXPECTED_SCHEMA:
        raise LifecycleEvidenceError("schema_version_mismatch")
    if (
        envelope.get("schema_id") != EXPECTED_SCHEMA_ID
        or envelope.get("dataschema") != EXPECTED_SCHEMA_ID
    ):
        raise LifecycleEvidenceError("schema_id_mismatch")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise LifecycleEvidenceError("event_data_invalid")
    if data.get("contract_version") != EXPECTED_SCHEMA:
        raise LifecycleEvidenceError("contract_version_mismatch")
    producer = data.get("producer")
    if (
        not isinstance(producer, dict)
        or producer.get("service_id") != EXPECTED_PRODUCER
        or producer.get("service_number") != 9
        or not isinstance(producer.get("instance_id"), str)
        or not producer["instance_id"]
    ):
        raise LifecycleEvidenceError("producer_identity_mismatch")
    if envelope.get("producer_id") != EXPECTED_PRODUCER:
        raise LifecycleEvidenceError("envelope_producer_mismatch")
    if envelope.get("id") != data.get("event_id"):
        raise LifecycleEvidenceError("event_id_mismatch")

    integrity = data.get("integrity")
    if not isinstance(integrity, dict):
        raise LifecycleEvidenceError("integrity_missing")
    expected_fields = {
        "canonicalization",
        "payload_sha256",
        "signature_algorithm",
        "key_id",
        "signature",
        "signed_at",
    }
    if set(integrity) != expected_fields:
        raise LifecycleEvidenceError("integrity_fields_invalid")
    if integrity.get("canonicalization") != "RFC8785":
        raise LifecycleEvidenceError("canonicalization_unsupported")
    if integrity.get("signature_algorithm") != "Ed25519":
        raise LifecycleEvidenceError("signature_algorithm_unsupported")
    key_id = integrity.get("key_id")
    if not isinstance(key_id, str) or not key_id:
        raise LifecycleEvidenceError("key_id_missing")
    try:
        key_bundle = json.loads(public_keys_json)
    except json.JSONDecodeError as exc:
        raise LifecycleEvidenceError("trust_bundle_invalid") from exc
    if not isinstance(key_bundle, dict) or key_id not in key_bundle:
        raise LifecycleEvidenceError("signing_key_untrusted")
    try:
        public_raw = base64.b64decode(key_bundle[key_id], validate=True)
        signature = base64.b64decode(integrity["signature"], validate=True)
    except (ValueError, TypeError) as exc:
        raise LifecycleEvidenceError("signature_encoding_invalid") from exc
    if len(public_raw) != 32 or len(signature) != 64:
        raise LifecycleEvidenceError("signature_length_invalid")
    signed_projection = {key: value for key, value in data.items() if key != "integrity"}
    try:
        canonical = rfc8785.dumps(signed_projection)
    except (TypeError, ValueError) as exc:
        raise LifecycleEvidenceError("canonical_payload_invalid") from exc
    digest = hashlib.sha256(canonical).hexdigest()
    if not isinstance(integrity.get("payload_sha256"), str) or not hmac.compare_digest(
        integrity["payload_sha256"], digest
    ):
        raise LifecycleEvidenceError("payload_digest_mismatch")
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, bytes.fromhex(digest))
    except (InvalidSignature, ValueError) as exc:
        raise LifecycleEvidenceError("signature_verification_failed") from exc

    instrument = data.get("instrument")
    if (
        not isinstance(instrument, dict)
        or not isinstance(instrument.get("canonical_id"), str)
        or len(instrument["canonical_id"]) != 6
        or not instrument["canonical_id"].isalpha()
        or not instrument["canonical_id"].isupper()
        or instrument["canonical_id"]
        != instrument.get("base_currency", "") + instrument.get("quote_currency", "")
    ):
        raise LifecycleEvidenceError("instrument_identity_invalid")
    if not isinstance(data.get("timeframe"), str) or not data["timeframe"]:
        raise LifecycleEvidenceError("timeframe_missing")
    lifecycle = data.get("lifecycle")
    if (
        not isinstance(lifecycle, dict)
        or not isinstance(lifecycle.get("lifecycle_id"), str)
        or not lifecycle.get("lifecycle_id")
        or lifecycle.get("transition_id") != data.get("event_id")
    ):
        raise LifecycleEvidenceError("lifecycle_identity_invalid")
    history = lifecycle.get("transition_history")
    if not isinstance(history, list) or not history or len(history) > 100:
        raise LifecycleEvidenceError("transition_history_invalid")
    previous_hash = "0" * 64
    previous_time: datetime | None = None
    previous_state_rank = -1
    seen_transition_ids: set[str] = set()
    transition_state_ranks = {
        "SWEEP_CONFIRMED": 0,
        "SWEEP_CONFIRMED_AWAITING_DISPLACEMENT": 0,
        "DISPLACEMENT_CONFIRMED": 1,
        "MIDPOINT_REACHED": 2,
        "CONSOLIDATION_CANDIDATE": 3,
        "MIDPOINT_CONSOLIDATION_CANDIDATE": 3,
        "INVALIDATED": 4,
    }
    for expected_sequence, item in enumerate(history, start=1):
        if not isinstance(item, dict) or set(item) != {
            "lifecycle_id", "transition_id", "sequence", "state",
            "occurred_at", "previous_transition_sha256", "transition_sha256",
        }:
            raise LifecycleEvidenceError("transition_history_entry_invalid")
        current_state_rank = transition_state_ranks.get(item.get("state"), -1) if isinstance(item, dict) else -1
        progression_skips_required_state = (
            previous_state_rank >= 0
            and current_state_rank != 4
            and current_state_rank != previous_state_rank + 1
        )
        if (
            item.get("lifecycle_id") != lifecycle.get("lifecycle_id")
            or item.get("sequence") != expected_sequence
            or isinstance(item.get("sequence"), bool)
            or not isinstance(item.get("state"), str)
            or current_state_rank <= previous_state_rank
            or progression_skips_required_state
            or item.get("previous_transition_sha256") != previous_hash
        ):
            raise LifecycleEvidenceError("transition_history_order_invalid")
        previous_state_rank = current_state_rank
        occurred = _parse_utc(item.get("occurred_at"), "transition_occurred_at")
        if previous_time is not None and occurred < previous_time:
            raise LifecycleEvidenceError("transition_history_time_regression")
        expected_id = hashlib.sha256(
            f"{lifecycle['lifecycle_id']}|{expected_sequence}|{item['state']}|{item['occurred_at']}".encode("utf-8")
        ).hexdigest()
        if item.get("transition_id") != expected_id or expected_id in seen_transition_ids:
            raise LifecycleEvidenceError("transition_identity_invalid")
        projection = {
            "lifecycle_id": item["lifecycle_id"],
            "transition_id": item["transition_id"],
            "sequence": item["sequence"],
            "state": item["state"],
            "occurred_at": item["occurred_at"],
            "previous_transition_sha256": item["previous_transition_sha256"],
        }
        calculated_hash = hashlib.sha256(rfc8785.dumps(projection)).hexdigest()
        if not isinstance(item.get("transition_sha256"), str) or not hmac.compare_digest(
            item["transition_sha256"], calculated_hash
        ):
            raise LifecycleEvidenceError("transition_hash_chain_invalid")
        previous_hash = calculated_hash
        previous_time = occurred
        seen_transition_ids.add(expected_id)
    final_transition = history[-1]
    if (
        lifecycle.get("transition_sequence") != final_transition["sequence"]
        or lifecycle.get("transition_sha256") != final_transition["transition_sha256"]
        or lifecycle.get("previous_transition_sha256") != final_transition["previous_transition_sha256"]
        or lifecycle.get("transition_id") != final_transition["transition_id"]
        or data.get("event_id") != final_transition["transition_id"]
        or lifecycle.get("state") != final_transition["state"]
    ):
        raise LifecycleEvidenceError("transition_head_mismatch")
    provenance = data.get("provenance")
    if (
        not isinstance(provenance, dict)
        or not isinstance(provenance.get("source_payload_sha256"), str)
        or len(provenance["source_payload_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in provenance["source_payload_sha256"])
        or not isinstance(provenance.get("lineage"), list)
        or not provenance["lineage"]
    ):
        raise LifecycleEvidenceError("provenance_invalid")
    temporal = data.get("temporal")
    if not isinstance(temporal, dict):
        raise LifecycleEvidenceError("temporal_missing")
    source_at = _parse_utc(temporal.get("source_candle_at"), "source_candle_at")
    observed_at = _parse_utc(temporal.get("observed_at"), "observed_at")
    confirmed_at = _parse_utc(temporal.get("confirmed_at"), "confirmed_at")
    produced_at = _parse_utc(temporal.get("produced_at"), "produced_at")
    available_at = _parse_utc(temporal.get("available_at"), "available_at")
    signed_at = _parse_utc(integrity.get("signed_at"), "signed_at")
    if not source_at <= observed_at <= confirmed_at <= produced_at <= available_at:
        raise LifecycleEvidenceError("temporal_order_invalid")
    if signed_at < produced_at or signed_at > available_at:
        raise LifecycleEvidenceError("signature_time_invalid")
    now = datetime.now(UTC)
    if available_at > now.replace(microsecond=0) + timedelta(seconds=clock_skew_seconds):
        raise LifecycleEvidenceError("availability_time_in_future")
    quality = data.get("quality")
    if not isinstance(quality, dict) or quality.get("quality_status") not in {
        "PASS",
        "DEGRADED",
        "FAIL",
        "UNKNOWN",
    }:
        raise LifecycleEvidenceError("quality_metadata_invalid")
    # The current Service 9 input API accepts caller-supplied candles. Its
    # signature is producer-authentic, not a vendor/source attestation.
    source_verified = _verify_service1_source_attestation(data, source_public_keys_json)
    return {
        "event_id": data["event_id"],
        "lifecycle_id": lifecycle["lifecycle_id"],
        "transition_sequence": final_transition["sequence"],
        "transition_sha256": final_transition["transition_sha256"],
        "transition_head_sha256": final_transition["transition_sha256"],
        "payload_sha256": digest,
        "key_id": key_id,
        "available_at": available_at.isoformat(),
        "instrument": instrument["canonical_id"],
        "timeframe": data["timeframe"],
        "source_dataset_id": data["provenance"]["source_dataset_id"],
        "price_basis": data["market_basis"]["price_basis"],
        "source_verified": source_verified,
        "signature_verified": True,
    }


class LifecycleEvidenceInbox:
    """Durable inbox with immutable event records and explicit quarantine."""

    def __init__(
        self,
        path: str,
        *,
        public_keys_json: str = "{}",
        source_public_keys_json: str = "{}",
        clock_skew_seconds: int = 60,
    ) -> None:
        self.path = path
        self.public_keys_json = public_keys_json
        self.source_public_keys_json = source_public_keys_json
        self.clock_skew_seconds = clock_skew_seconds
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _verify_persisted_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """Reverify signed bytes and indexed metadata on every replay read."""
        try:
            envelope = json.loads(row["envelope_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise LifecycleEvidenceError("persisted_envelope_corrupt") from exc
        verified = verify_lifecycle_event(
            envelope,
            public_keys_json=self.public_keys_json,
            source_public_keys_json=self.source_public_keys_json,
            clock_skew_seconds=self.clock_skew_seconds,
        )
        if (
            verified["event_id"] != row["event_id"]
            or not hmac.compare_digest(verified["payload_sha256"], row["payload_sha256"])
            or verified["instrument"] != row["instrument"]
            or verified["timeframe"] != row["timeframe"]
            or verified["lifecycle_id"] != row["lifecycle_id"]
            or verified["transition_sequence"] != row["transition_sequence"]
            or verified["transition_sha256"] != row["transition_sha256"]
            or not bool(row["signature_verified"])
            or not bool(row["source_verified"])
        ):
            raise LifecycleEvidenceError("persisted_evidence_integrity_mismatch")
        return envelope

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS lifecycle_evidence_inbox (
                    event_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signature_verified INTEGER NOT NULL,
                    source_verified INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    available_at_epoch_us INTEGER,
                    received_at_epoch_us INTEGER,
                    lifecycle_id TEXT,
                    transition_sequence INTEGER,
                    transition_sha256 TEXT
                )
            """)
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(lifecycle_evidence_inbox)"
                )
            }
            if "available_at_epoch_us" not in columns:
                connection.execute(
                    "ALTER TABLE lifecycle_evidence_inbox ADD COLUMN available_at_epoch_us INTEGER"
                )
            if "received_at_epoch_us" not in columns:
                connection.execute(
                    "ALTER TABLE lifecycle_evidence_inbox ADD COLUMN received_at_epoch_us INTEGER"
                )
            if "lifecycle_id" not in columns:
                connection.execute(
                    "ALTER TABLE lifecycle_evidence_inbox ADD COLUMN lifecycle_id TEXT"
                )
            if "transition_sequence" not in columns:
                connection.execute(
                    "ALTER TABLE lifecycle_evidence_inbox ADD COLUMN transition_sequence INTEGER"
                )
            if "transition_sha256" not in columns:
                connection.execute(
                    "ALTER TABLE lifecycle_evidence_inbox ADD COLUMN transition_sha256 TEXT"
                )
            # Legacy rows predate signed transition chains. Keep them for audit,
            # but revoke their feature eligibility rather than silently trusting them.
            connection.execute(
                "UPDATE lifecycle_evidence_inbox SET source_verified=0 "
                "WHERE source_verified!=0 AND (lifecycle_id IS NULL OR transition_sequence IS NULL "
                "OR transition_sha256 IS NULL)"
            )

            legacy_rows = connection.execute(
                "SELECT rowid,available_at,received_at FROM lifecycle_evidence_inbox "
                "WHERE available_at_epoch_us IS NULL OR received_at_epoch_us IS NULL"
            ).fetchall()
            for legacy in legacy_rows:
                available = _parse_utc(legacy["available_at"], "available_at")
                received = _parse_utc(legacy["received_at"], "received_at")
                connection.execute(
                    "UPDATE lifecycle_evidence_inbox SET available_at_epoch_us=?,"
                    "received_at_epoch_us=? WHERE rowid=?",
                    (
                        _epoch_microseconds(available),
                        _epoch_microseconds(received),
                        legacy["rowid"],
                    ),
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_lifecycle_lifecycle_sequence "
                "ON lifecycle_evidence_inbox(lifecycle_id,transition_sequence) "
                "WHERE lifecycle_id IS NOT NULL AND transition_sequence IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_lifecycle_evidence_point_in_time "
                "ON lifecycle_evidence_inbox(instrument,timeframe,available_at_epoch_us,received_at_epoch_us)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS lifecycle_evidence_conflicts (
                    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS lifecycle_evidence_quarantine (
                    delivery_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    envelope_json TEXT NOT NULL,
                    rejection_reason TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_lifecycle_inbox_no_update
                BEFORE UPDATE ON lifecycle_evidence_inbox
                BEGIN SELECT RAISE(ABORT, 'lifecycle inbox evidence is immutable'); END
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_lifecycle_inbox_no_delete
                BEFORE DELETE ON lifecycle_evidence_inbox
                BEGIN SELECT RAISE(ABORT, 'lifecycle inbox evidence is immutable'); END
            """)


    def persist_verified(
        self, topic: str, envelope: dict[str, Any], verified: dict[str, Any]
    ) -> str:
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_sha256 FROM lifecycle_evidence_inbox WHERE event_id=?",
                (verified["event_id"],),
            ).fetchone()
            if existing is not None:
                if hmac.compare_digest(existing["payload_sha256"], verified["payload_sha256"]):
                    return "DUPLICATE"
                connection.execute(
                    "INSERT INTO lifecycle_evidence_conflicts(event_id,payload_sha256,envelope_json,received_at) VALUES(?,?,?,?)",
                    (verified["event_id"], verified["payload_sha256"], encoded, now),
                )
                return "CONFLICT"
            sequence_existing = connection.execute(
                "SELECT event_id,transition_sha256 FROM lifecycle_evidence_inbox "
                "WHERE lifecycle_id=? AND transition_sequence=?",
                (verified["lifecycle_id"], verified["transition_sequence"]),
            ).fetchone()
            if sequence_existing is not None:
                connection.execute(
                    "INSERT INTO lifecycle_evidence_conflicts(event_id,payload_sha256,envelope_json,received_at) VALUES(?,?,?,?)",
                    (verified["event_id"], verified["payload_sha256"], encoded, now),
                )
                return "CONFLICT"
            connection.execute(
                """
                INSERT INTO lifecycle_evidence_inbox(
                    event_id,topic,envelope_json,payload_sha256,key_id,available_at,
                    instrument,timeframe,signature_verified,source_verified,received_at,
                    available_at_epoch_us,received_at_epoch_us,lifecycle_id,
                    transition_sequence,transition_sha256
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    verified["event_id"], topic, encoded, verified["payload_sha256"],
                    verified["key_id"], verified["available_at"], verified["instrument"],
                    verified["timeframe"], 1, int(verified["source_verified"]), now,
                    _epoch_microseconds(_parse_utc(verified["available_at"], "available_at")),
                    _epoch_microseconds(datetime.fromisoformat(now)),
                    verified["lifecycle_id"], verified["transition_sequence"],
                    verified["transition_sha256"],
                ),
            )
            return "STORED"

    def persist_rejected(
        self, delivery_id: str, event_id: str | None, envelope: dict[str, Any], reason: str
    ) -> None:
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO lifecycle_evidence_quarantine(delivery_id,event_id,envelope_json,rejection_reason,received_at) VALUES(?,?,?,?,?)",
                (delivery_id, event_id, encoded, reason[:500], datetime.now(UTC).isoformat()),
            )

    def point_in_time_contexts(
        self,
        *,
        instrument: str,
        timeframe: str,
        source_dataset_id: str,
        price_basis: str,
        cutoffs: list[datetime],
    ) -> list[dict[str, float] | None]:
        """Build causal features at each origin using exact UTC instants.

        Epoch microseconds avoid both lexical ISO-8601 ordering errors (Z
        versus +00:00) and the millisecond precision limit of SQLite julianday.
        Producer availability and durable inbox receipt are independently
        checked. Results preserve the caller's original cutoff order.
        """
        if not cutoffs:
            return []

        indexed_cutoffs: list[tuple[int, datetime]] = []
        for index, cutoff in enumerate(cutoffs):
            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                raise ValueError("point-in-time replay cutoffs must be timezone-aware")
            indexed_cutoffs.append((index, cutoff.astimezone(UTC)))

        max_cutoff_us = max(
            _epoch_microseconds(value) for _, value in indexed_cutoffs
        )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id,envelope_json,payload_sha256,key_id,available_at,received_at,
                       instrument,timeframe,signature_verified,source_verified,lifecycle_id,
                       transition_sequence,transition_sha256
                FROM lifecycle_evidence_inbox
                WHERE source_verified=1 AND instrument=? AND timeframe=?
                  AND json_extract(envelope_json, '$.data.provenance.source_dataset_id')=?
                  AND available_at_epoch_us<=?
                  AND received_at_epoch_us<=?
                """,
                (instrument, timeframe, source_dataset_id, max_cutoff_us, max_cutoff_us),
            ).fetchall()

        events: list[tuple[datetime, str, str, int, datetime, dict[str, Any]]] = []
        for row in rows:
            envelope = self._verify_persisted_row(row)
            data = envelope.get("data") if isinstance(envelope, dict) else None
            if not isinstance(data, dict):
                continue
            market_basis = data.get("market_basis")
            temporal = data.get("temporal")
            lifecycle = data.get("lifecycle")
            if (
                not isinstance(market_basis, dict)
                or market_basis.get("price_basis") != price_basis
                or not isinstance(temporal, dict)
                or not isinstance(lifecycle, dict)
            ):
                continue
            producer_available_at = _parse_utc(temporal.get("available_at"), "available_at")
            inbox_received_at = _parse_utc(row["received_at"], "inbox_received_at")
            observed_at = _parse_utc(temporal.get("observed_at"), "observed_at")
            effective_at = max(producer_available_at, inbox_received_at)
            if _epoch_microseconds(effective_at) <= max_cutoff_us:
                events.append((
                    effective_at, str(data.get("event_id", "")),
                    str(lifecycle.get("lifecycle_id", "")),
                    int(lifecycle.get("transition_sequence", 0)), observed_at, data,
                ))

        # Delivery order is not lifecycle order. A late lower-sequence event
        # must never roll a lifecycle snapshot backwards.
        events.sort(key=lambda item: (item[0], item[1]))
        ordered_cutoffs = sorted(indexed_cutoffs, key=lambda item: (item[1], item[0]))
        contexts: list[dict[str, float] | None] = [None] * len(cutoffs)
        event_index = 0
        latest_by_lifecycle: dict[str, tuple[int, datetime, dict[str, Any]]] = {}
        for original_index, normalized_cutoff in ordered_cutoffs:
            while event_index < len(events) and events[event_index][0] <= normalized_cutoff:
                _, _, lifecycle_id, sequence, observed_at, data = events[event_index]
                current = latest_by_lifecycle.get(lifecycle_id)
                if current is None or sequence > current[0]:
                    latest_by_lifecycle[lifecycle_id] = (sequence, observed_at, data)
                event_index += 1
            latest_entry = max(
                latest_by_lifecycle.values(),
                key=lambda item: (item[1], item[0], str(item[2].get("event_id", ""))),
                default=None,
            )
            if latest_entry is None:
                contexts[original_index] = None
                continue
            latest = latest_entry[2]
            lifecycle = latest.get("lifecycle", {})
            contexts[original_index] = {
                "liquidity_sweep_bullish": float(lifecycle.get("direction") == "BULLISH"),
                "liquidity_sweep_bearish": float(lifecycle.get("direction") == "BEARISH"),
                "liquidity_displacement_confirmed": float(
                    lifecycle.get("displacement_confirmed_at") is not None
                ),
                "liquidity_midpoint_reached": float(
                    lifecycle.get("midpoint_first_reached_at") is not None
                ),
                "liquidity_midpoint_consolidation": float(
                    lifecycle.get("consolidation_candidate_at") is not None
                ),
                "liquidity_invalidated": float(lifecycle.get("invalidated_at") is not None),
            }
        return contexts

    def point_in_time_evidence(
        self,
        *,
        instrument: str,
        timeframe: str,
        source_dataset_id: str,
        price_basis: str,
        cutoffs: list[datetime],
    ) -> list[dict[str, Any]]:
        """Return an auditable evidence manifest for each prediction origin."""
        indexed: list[tuple[int, datetime]] = []
        for index, cutoff in enumerate(cutoffs):
            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                raise ValueError("point-in-time replay cutoffs must be timezone-aware")
            indexed.append((index, cutoff.astimezone(UTC)))
        if not indexed:
            return []
        max_us = max(_epoch_microseconds(value) for _, value in indexed)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id,envelope_json,payload_sha256,key_id,available_at,received_at,
                       instrument,timeframe,signature_verified,source_verified,lifecycle_id,
                       transition_sequence,transition_sha256,available_at_epoch_us,received_at_epoch_us
                FROM lifecycle_evidence_inbox
                WHERE source_verified=1 AND instrument=? AND timeframe=?
                  AND json_extract(envelope_json, '$.data.provenance.source_dataset_id')=?
                  AND available_at_epoch_us<=? AND received_at_epoch_us<=?
                """,
                (instrument, timeframe, source_dataset_id, max_us, max_us),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            envelope = self._verify_persisted_row(row)
            data = envelope.get("data", {})
            lifecycle = data.get("lifecycle", {})
            temporal = data.get("temporal", {})
            basis = data.get("market_basis", {})
            if basis.get("price_basis") != price_basis:
                continue
            producer_at = _parse_utc(temporal.get("available_at"), "available_at")
            received_at = _parse_utc(row["received_at"], "received_at")
            events.append({
                "event_id": row["event_id"],
                "payload_sha256": row["payload_sha256"],
                "lifecycle_id": lifecycle.get("lifecycle_id"),
                "transition_sequence": int(lifecycle.get("transition_sequence", 0)),
                "transition_sha256": lifecycle.get("transition_sha256"),
                "observed_at": _parse_utc(temporal.get("observed_at"), "observed_at"),
                "producer_available_at": producer_at,
                "consumer_received_at": received_at,
                "effective_available_at": max(producer_at, received_at),
            })
        events.sort(key=lambda item: (item["effective_available_at"], item["event_id"]))
        ordered = sorted(indexed, key=lambda item: (item[1], item[0]))
        output: list[dict[str, Any] | None] = [None] * len(cutoffs)
        by_lifecycle: dict[str, dict[str, Any]] = {}
        cursor = 0
        for original_index, origin in ordered:
            while cursor < len(events) and events[cursor]["effective_available_at"] <= origin:
                item = events[cursor]
                lifecycle_id = str(item["lifecycle_id"])
                previous = by_lifecycle.get(lifecycle_id)
                if previous is None or item["transition_sequence"] > previous["transition_sequence"]:
                    by_lifecycle[lifecycle_id] = item
                cursor += 1
            manifest = sorted(
                by_lifecycle.values(),
                key=lambda item: (item["observed_at"], item["lifecycle_id"]),
            )
            canonical_manifest = [
                {
                    "event_id": item["event_id"],
                    "payload_sha256": item["payload_sha256"],
                    "lifecycle_id": item["lifecycle_id"],
                    "transition_sequence": item["transition_sequence"],
                    "transition_sha256": item["transition_sha256"],
                    "producer_available_at": item["producer_available_at"].isoformat(),
                    "consumer_received_at": item["consumer_received_at"].isoformat(),
                }
                for item in manifest
            ]
            manifest_digest = hashlib.sha256(
                rfc8785.dumps(canonical_manifest)
            ).hexdigest()
            output[original_index] = {
                "prediction_origin": origin.isoformat(),
                "instrument": instrument,
                "timeframe": timeframe,
                "source_dataset_id": source_dataset_id,
                "price_basis": price_basis,
                "evidence_count": len(canonical_manifest),
                "evidence": canonical_manifest,
                "evidence_set_sha256": manifest_digest,
            }
        return [item if item is not None else {
            "prediction_origin": cutoff.astimezone(UTC).isoformat(),
            "instrument": instrument,
            "timeframe": timeframe,
            "source_dataset_id": source_dataset_id,
            "price_basis": price_basis,
            "evidence_count": 0,
            "evidence": [],
            "evidence_set_sha256": hashlib.sha256(rfc8785.dumps([])).hexdigest(),
        } for item, cutoff in zip(output, cutoffs)]

    def lifecycle_history(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Reconstruct the signed transition chain for one lifecycle aggregate."""
        if not lifecycle_id or len(lifecycle_id) > 200:
            raise ValueError("lifecycle_id must contain 1 to 200 characters")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id,envelope_json,payload_sha256,key_id,available_at,received_at,
                       instrument,timeframe,signature_verified,source_verified,lifecycle_id,
                       transition_sequence,transition_sha256
                FROM lifecycle_evidence_inbox
                WHERE lifecycle_id=? AND source_verified=1
                ORDER BY transition_sequence DESC
                """,
                (lifecycle_id,),
            ).fetchall()
        if not rows:
            return None
        latest_row = rows[0]
        envelope = self._verify_persisted_row(latest_row)
        data = envelope["data"]
        history = data["lifecycle"]["transition_history"]
        stored_events = []
        for row in reversed(rows):
            self._verify_persisted_row(row)
            stored_events.append({
                "event_id": row["event_id"],
                "payload_sha256": row["payload_sha256"],
                "transition_sequence": row["transition_sequence"],
                "transition_sha256": row["transition_sha256"],
                "producer_available_at": row["available_at"],
                "consumer_received_at": row["received_at"],
            })
        return {
            "lifecycle_id": lifecycle_id,
            "head_event_id": latest_row["event_id"],
            "head_sequence": latest_row["transition_sequence"],
            "head_transition_sha256": latest_row["transition_sha256"],
            "reconstructed_transition_history": history,
            "individually_received_transition_events": stored_events,
            "history_complete_in_signed_head": True,
            "signature_reverified": True,
        }

    def status(self) -> dict[str, int]:
        with self._connect() as connection:
            accepted_row = connection.execute(
                "SELECT COUNT(*) AS n FROM lifecycle_evidence_inbox"
            ).fetchone()
            source_row = connection.execute(
                "SELECT COUNT(*) AS n FROM lifecycle_evidence_inbox WHERE source_verified=1"
            ).fetchone()
            conflict_row = connection.execute(
                "SELECT COUNT(*) AS n FROM lifecycle_evidence_conflicts"
            ).fetchone()
            rejected_row = connection.execute(
                "SELECT COUNT(*) AS n FROM lifecycle_evidence_quarantine"
            ).fetchone()
            history_row = connection.execute(
                "SELECT COUNT(DISTINCT lifecycle_id) AS lifecycles,"
                "COALESCE(MAX(transition_sequence),0) AS max_sequence "
                "FROM lifecycle_evidence_inbox WHERE source_verified=1"
            ).fetchone()
            accepted = int(accepted_row["n"]) if accepted_row else 0
            source_verified = int(source_row["n"]) if source_row else 0
            conflicts = int(conflict_row["n"]) if conflict_row else 0
            rejected = int(rejected_row["n"]) if rejected_row else 0
            lifecycle_count = int(history_row["lifecycles"]) if history_row else 0
            max_sequence = int(history_row["max_sequence"]) if history_row else 0
        return {
            "signature_verified_events": int(accepted),
            "source_attested_events": int(source_verified),
            "conflicts": int(conflicts),
            "quarantined_deliveries": int(rejected),
            "unique_lifecycle_aggregates": lifecycle_count,
            "highest_transition_sequence": max_sequence,
            "persisted_signatures_reverified_on_replay": True,
            "replay_fails_closed_on_integrity_error": True,
        }


class LifecycleEvidenceConsumer:
    """Poll Service 62 and acknowledge only after durable inbox persistence."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.inbox = LifecycleEvidenceInbox(
            settings.lifecycle_event_inbox_db_path,
            public_keys_json=settings.lifecycle_event_public_keys_json,
            source_public_keys_json=settings.upstream_historical_attestation_public_keys_json,
            clock_skew_seconds=settings.lifecycle_event_clock_skew_seconds,
        )
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def _token(self) -> str:
        now = int(time.time())
        subject = "fx-historical-market-analysis-service"
        body = json.dumps(
            {
                "sub": subject,
                "role": "consumer",
                "iat": now,
                "exp": now + 300,
                "jti": str(uuid.uuid4()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        secret = (self.settings.lifecycle_event_bus_consumer_secret or "").encode("utf-8")
        signature = hmac.new(secret, body, hashlib.sha256).digest()
        return _b64url_encode(body) + "." + _b64url_encode(signature)

    async def start(self) -> None:
        if not self.settings.lifecycle_event_bus_enabled:
            return
        base_url = self.settings.lifecycle_event_bus_url or ""
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(8.0, connect=3.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="service2-lifecycle-evidence-consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.consume_once()
            except (httpx.HTTPError, ValueError, RuntimeError, sqlite3.Error) as exc:
                logger.warning("lifecycle_evidence_poll_failed", extra={"error": str(exc)[:300]})
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.lifecycle_event_poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def consume_once(self) -> int:
        if self._client is None:
            return 0
        response = await self._client.post(
            "/api/v1/consume",
            headers={"X-Auth-Token": self._token()},
            json={
                "topic": self.settings.lifecycle_event_bus_topic,
                "consumer_group": self.settings.lifecycle_event_consumer_group,
                "max_messages": self.settings.lifecycle_event_batch_size,
            },
        )
        response.raise_for_status()
        body = response.json()
        messages = body.get("messages", []) if isinstance(body, dict) else []
        if not isinstance(messages, list):
            raise RuntimeError("Event Bus consume response messages must be a list")
        processed = 0
        for message in messages:
            if not isinstance(message, dict):
                continue
            delivery = message.get("delivery", {})
            if not isinstance(delivery, dict):
                continue
            delivery_id = delivery.get("delivery_id")
            envelope = message.get("envelope", {})
            if not isinstance(delivery_id, str):
                continue
            if not isinstance(envelope, dict):
                self.inbox.persist_rejected(delivery_id, None, {}, "envelope_invalid")
                await self._ack(delivery_id, negative=False)
                processed += 1
                continue
            event_id = envelope.get("id") if isinstance(envelope.get("id"), str) else None
            try:
                verified = verify_lifecycle_event(
                    envelope,
                    public_keys_json=self.settings.lifecycle_event_public_keys_json,
                    clock_skew_seconds=self.settings.lifecycle_event_clock_skew_seconds,
                    source_public_keys_json=self.settings.upstream_historical_attestation_public_keys_json,
                )
                self.inbox.persist_verified(
                    self.settings.lifecycle_event_bus_topic, envelope, verified
                )
            except LifecycleEvidenceError as exc:
                try:
                    self.inbox.persist_rejected(delivery_id, event_id, envelope, str(exc))
                except sqlite3.Error:
                    await self._ack(delivery_id, negative=True)
                    continue
            except sqlite3.Error:
                await self._ack(delivery_id, negative=True)
                continue
            await self._ack(delivery_id, negative=False)
            processed += 1
        return processed

    async def _ack(self, delivery_id: str, *, negative: bool) -> None:
        if self._client is None:
            return
        endpoint = "/api/v1/nack" if negative else "/api/v1/ack"
        response = await self._client.post(
            endpoint,
            headers={"X-Auth-Token": self._token()},
            json={
                "topic": self.settings.lifecycle_event_bus_topic,
                "consumer_group": self.settings.lifecycle_event_consumer_group,
                "delivery_id": delivery_id,
            },
        )
        response.raise_for_status()

    def point_in_time_contexts(
        self,
        *,
        instrument: str,
        timeframe: str,
        source_dataset_id: str,
        price_basis: str,
        cutoffs: list[datetime],
    ) -> list[dict[str, float] | None]:
        return self.inbox.point_in_time_contexts(
            instrument=instrument,
            timeframe=timeframe,
            source_dataset_id=source_dataset_id,
            price_basis=price_basis,
            cutoffs=cutoffs,
        )

    def point_in_time_evidence(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.inbox.point_in_time_evidence(**kwargs)

    def lifecycle_history(self, lifecycle_id: str) -> dict[str, Any] | None:
        return self.inbox.lifecycle_history(lifecycle_id)

    def status(self) -> dict[str, Any]:
        inbox_status = self.inbox.status()
        source_attested = inbox_status["source_attested_events"] > 0
        return {
            "enabled": self.settings.lifecycle_event_bus_enabled,
            "topic": self.settings.lifecycle_event_bus_topic,
            "consumer_group": self.settings.lifecycle_event_consumer_group,
            "inbox": inbox_status,
            "forecast_eligible": False,
            "source_attested_events_available": source_attested,
            "transition_chain_verification": "independent_ed25519_and_rfc8785_sha256",
            "replay_evidence_manifests": "per_prediction_origin",
            "persisted_record_reverification": "enabled",
            "reason": (
                "Source-attested events are available; feature eligibility is determined per replay origin using exact dataset, instrument, timeframe, price basis and producer/inbox availability. This is not a vendor-origin signature."
                if source_attested
                else "No source-attested lifecycle events are stored; caller-supplied lifecycle assertions remain excluded from model features."
            ),
        }
