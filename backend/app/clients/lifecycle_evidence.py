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
    if not isinstance(lifecycle, dict) or lifecycle.get("lifecycle_id") != data.get("event_id"):
        raise LifecycleEvidenceError("lifecycle_identity_invalid")
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

    def __init__(self, path: str) -> None:
        self.path = path
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
                    received_at TEXT NOT NULL
                )
            """)
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
            connection.execute(
                """
                INSERT INTO lifecycle_evidence_inbox(
                    event_id,topic,envelope_json,payload_sha256,key_id,available_at,
                    instrument,timeframe,signature_verified,source_verified,received_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    verified["event_id"],
                    topic,
                    encoded,
                    verified["payload_sha256"],
                    verified["key_id"],
                    verified["available_at"],
                    verified["instrument"],
                    verified["timeframe"],
                    1,
                    int(verified["source_verified"]),
                    now,
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
        """Build features using producer availability and durable inbox receipt cutoffs."""
        if not cutoffs:
            return []
        max_cutoff = max(cutoffs).astimezone(UTC).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT envelope_json,available_at,received_at FROM lifecycle_evidence_inbox
                WHERE source_verified=1 AND instrument=? AND timeframe=?
                  AND json_extract(envelope_json, '$.data.provenance.source_dataset_id')=?
                  AND available_at<=? AND received_at<=?
                ORDER BY CASE WHEN received_at > available_at THEN received_at ELSE available_at END ASC
                """,
                (instrument, timeframe, source_dataset_id, max_cutoff, max_cutoff),
            ).fetchall()
        events: list[tuple[datetime, dict[str, Any]]] = []
        for row in rows:
            envelope = json.loads(row["envelope_json"])
            data = envelope.get("data") if isinstance(envelope, dict) else None
            if not isinstance(data, dict):
                continue
            market_basis = data.get("market_basis")
            temporal = data.get("temporal")
            if (
                not isinstance(market_basis, dict)
                or market_basis.get("price_basis") != price_basis
                or not isinstance(temporal, dict)
            ):
                continue
            producer_available_at = _parse_utc(temporal.get("available_at"), "available_at")
            inbox_received_at = _parse_utc(row["received_at"], "inbox_received_at")
            events.append((max(producer_available_at, inbox_received_at), data))

        contexts: list[dict[str, float] | None] = []
        event_index = 0
        latest: dict[str, Any] | None = None
        for cutoff in cutoffs:
            normalized_cutoff = cutoff.astimezone(UTC)
            while event_index < len(events) and events[event_index][0] <= normalized_cutoff:
                latest = events[event_index][1]
                event_index += 1
            if latest is None:
                contexts.append(None)
                continue
            lifecycle = latest.get("lifecycle", {})
            contexts.append(
                {
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
            )
        return contexts

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
            accepted = int(accepted_row["n"]) if accepted_row else 0
            source_verified = int(source_row["n"]) if source_row else 0
            conflicts = int(conflict_row["n"]) if conflict_row else 0
            rejected = int(rejected_row["n"]) if rejected_row else 0
        return {
            "signature_verified_events": int(accepted),
            "source_attested_events": int(source_verified),
            "conflicts": int(conflicts),
            "quarantined_deliveries": int(rejected),
        }


class LifecycleEvidenceConsumer:
    """Poll Service 62 and acknowledge only after durable inbox persistence."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.inbox = LifecycleEvidenceInbox(settings.lifecycle_event_inbox_db_path)
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
            "reason": (
                "Source-attested events are available; feature eligibility is determined per replay origin using exact dataset, instrument, timeframe, price basis and producer/inbox availability. This is not a vendor-origin signature."
                if source_attested
                else "No source-attested lifecycle events are stored; caller-supplied lifecycle assertions remain excluded from model features."
            ),
        }
