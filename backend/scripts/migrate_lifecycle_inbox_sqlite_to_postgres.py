#!/usr/bin/env python3
"""Idempotently copy a consistent SQLite lifecycle inbox snapshot into PostgreSQL.

Stop the Service 2 consumer before cutover. The SQLite backup API includes WAL
state and creates a transactionally consistent snapshot; never copy only the
live .sqlite3 file while WAL is active.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import rfc8785
from psycopg.rows import dict_row

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.clients.lifecycle_evidence import PostgresLifecycleEvidenceInbox  # noqa: E402


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("source inbox timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def epoch_us(value: str) -> int:
    normalized = parse_timestamp(value)
    delta = normalized - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def table_exists(db: sqlite3.Connection, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def rows(db: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    if not table_exists(db, table):
        return []
    return db.execute(f"SELECT * FROM {table}").fetchall()


def snapshot_sqlite(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite inbox not found: {path}")
    source = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
            snapshot_path = tmp.name
        target = sqlite3.connect(snapshot_path)
        try:
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise RuntimeError("SQLite snapshot failed PRAGMA integrity_check")
        except Exception:
            Path(snapshot_path).unlink(missing_ok=True)
            raise
        finally:
            target.close()
    finally:
        source.close()
    digest = hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest()
    return snapshot_path, digest


def migrate(sqlite_path: Path, dsn: str) -> dict[str, int | str]:
    inbox = PostgresLifecycleEvidenceInbox(dsn)
    del inbox  # constructor applies the versioned PostgreSQL schema under an advisory lock
    snapshot_path, fingerprint = snapshot_sqlite(sqlite_path)
    source: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(snapshot_path)
        source.row_factory = sqlite3.Row
        integrity = source.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("SQLite source snapshot failed PRAGMA integrity_check")
        inbox_rows = rows(source, "lifecycle_evidence_inbox")
        verification_rows = rows(source, "lifecycle_evidence_source_verifications")
        conflict_rows = rows(source, "lifecycle_evidence_conflicts")
        quarantine_rows = rows(source, "lifecycle_evidence_quarantine")

        imported = {"inbox": 0, "source_verifications": 0, "conflicts": 0, "quarantine": 0}
        with psycopg.connect(dsn, row_factory=dict_row) as target:
            target.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("fx-historical-market-analysis-service-lifecycle-inbox-sqlite-import-v1",),
            )
            target.execute("""
                CREATE TABLE IF NOT EXISTS lifecycle_evidence_imports (
                    source_fingerprint TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    imported_at TIMESTAMPTZ NOT NULL,
                    inbox_count BIGINT NOT NULL,
                    verification_count BIGINT NOT NULL,
                    conflict_count BIGINT NOT NULL,
                    quarantine_count BIGINT NOT NULL
                )
            """)
            already = target.execute(
                "SELECT 1 FROM lifecycle_evidence_imports WHERE source_fingerprint=%s",
                (fingerprint,),
            ).fetchone()
            if already:
                return {"status": "already_imported", "source_fingerprint": fingerprint}

            for row in inbox_rows:
                raw = dict(row)
                envelope_text = raw["envelope_json"]
                envelope = json.loads(envelope_text)
                if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
                    raise RuntimeError(f"Invalid lifecycle envelope in SQLite row {raw['event_id']}")
                data = envelope["data"]
                provenance = data.get("provenance", {})
                if not isinstance(provenance, dict):
                    raise RuntimeError(f"Invalid lifecycle provenance in SQLite row {raw['event_id']}")
                integrity_block = data.get("integrity", {})
                if not isinstance(integrity_block, dict):
                    raise RuntimeError(f"Missing lifecycle integrity block in SQLite row {raw['event_id']}")
                signed_projection = {key: value for key, value in data.items() if key != "integrity"}
                calculated_digest = hashlib.sha256(rfc8785.dumps(signed_projection)).hexdigest()
                if (
                    calculated_digest != raw["payload_sha256"]
                    or integrity_block.get("payload_sha256") != raw["payload_sha256"]
                ):
                    raise RuntimeError(f"SQLite lifecycle payload digest mismatch for {raw['event_id']}")
                source_dataset_id = provenance.get("source_dataset_id")
                stored_source_dataset_id = raw.get("source_dataset_id")
                if stored_source_dataset_id is not None and stored_source_dataset_id != source_dataset_id:
                    raise RuntimeError(f"SQLite source dataset index mismatch for {raw['event_id']}")
                available_calculated = epoch_us(raw["available_at"])
                received_calculated = epoch_us(raw["received_at"])
                available_stored = raw.get("available_at_epoch_us")
                received_stored = raw.get("received_at_epoch_us")
                if available_stored is not None and int(available_stored) != available_calculated:
                    raise RuntimeError(f"SQLite available_at index mismatch for {raw['event_id']}")
                if received_stored is not None and int(received_stored) != received_calculated:
                    raise RuntimeError(f"SQLite received_at index mismatch for {raw['event_id']}")
                available = available_calculated
                received = received_calculated
                values = (
                    raw["event_id"], raw["topic"], envelope_text, raw["payload_sha256"],
                    raw["key_id"], raw["available_at"], raw["instrument"], raw["timeframe"],
                    bool(raw["signature_verified"]), bool(raw["source_verified"]),
                    raw["received_at"], available, received, raw.get("lifecycle_id"),
                    raw.get("transition_sequence"), raw.get("transition_sha256"),
                    source_dataset_id,
                )
                target.execute("""
                    INSERT INTO lifecycle_evidence_inbox(
                        event_id,topic,envelope_json,payload_sha256,key_id,available_at,
                        instrument,timeframe,signature_verified,source_verified,received_at,
                        available_at_epoch_us,received_at_epoch_us,lifecycle_id,
                        transition_sequence,transition_sha256,source_dataset_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(event_id) DO NOTHING
                """, values)
                stored = target.execute(
                    """
                    SELECT topic,envelope_json,payload_sha256,key_id,available_at,instrument,
                           timeframe,signature_verified,source_verified,received_at,
                           available_at_epoch_us,received_at_epoch_us,lifecycle_id,
                           transition_sequence,transition_sha256,source_dataset_id
                    FROM lifecycle_evidence_inbox WHERE event_id=%s
                    """,
                    (raw["event_id"],),
                ).fetchone()
                expected = {
                    "topic": raw["topic"],
                    "envelope_json": envelope_text,
                    "payload_sha256": raw["payload_sha256"],
                    "key_id": raw["key_id"],
                    "available_at": raw["available_at"],
                    "instrument": raw["instrument"],
                    "timeframe": raw["timeframe"],
                    "signature_verified": bool(raw["signature_verified"]),
                    "source_verified": bool(raw["source_verified"]),
                    "received_at": raw["received_at"],
                    "available_at_epoch_us": available,
                    "received_at_epoch_us": received,
                    "lifecycle_id": raw.get("lifecycle_id"),
                    "transition_sequence": raw.get("transition_sequence"),
                    "transition_sha256": raw.get("transition_sha256"),
                    "source_dataset_id": source_dataset_id,
                }
                if stored is None or any(stored[key] != value for key, value in expected.items()):
                    raise RuntimeError(
                        f"PostgreSQL event conflict or indexed-metadata mismatch while importing {raw['event_id']}"
                    )
                imported["inbox"] += 1

            inbox_by_id = {dict(row)["event_id"]: dict(row) for row in inbox_rows}
            for row in verification_rows:
                raw = dict(row)
                parent = inbox_by_id.get(raw["event_id"])
                if (
                    parent is None
                    or parent["payload_sha256"] != raw["payload_sha256"]
                    or json.loads(parent["envelope_json"]).get("data", {}).get("provenance", {}).get("source_dataset_id")
                    != raw["source_dataset_id"]
                ):
                    raise RuntimeError(f"SQLite source-verification ledger is inconsistent for {raw['event_id']}")
                target.execute("""
                    INSERT INTO lifecycle_evidence_source_verifications(
                        event_id,source_dataset_id,payload_sha256,verified_at
                    ) VALUES (%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING
                """, (raw["event_id"], raw["source_dataset_id"], raw["payload_sha256"], raw["verified_at"]))
                stored = target.execute(
                    "SELECT source_dataset_id,payload_sha256,verified_at FROM lifecycle_evidence_source_verifications WHERE event_id=%s",
                    (raw["event_id"],),
                ).fetchone()
                if (
                    stored is None
                    or stored["source_dataset_id"] != raw["source_dataset_id"]
                    or stored["payload_sha256"] != raw["payload_sha256"]
                    or stored["verified_at"] != raw["verified_at"]
                ):
                    raise RuntimeError(f"PostgreSQL source-verification conflict for {raw['event_id']}")
                imported["source_verifications"] += 1

            for row in conflict_rows:
                raw = dict(row)
                conflict_envelope = json.loads(raw["envelope_json"])
                if not isinstance(conflict_envelope, dict):
                    raise RuntimeError(
                        f"SQLite conflict record {raw['conflict_id']} is not a JSON object"
                    )
                if conflict_envelope.get("kind") == "quarantine_delivery_id_reuse":
                    conflict_digest = hashlib.sha256(
                        raw["envelope_json"].encode("utf-8")
                    ).hexdigest()
                else:
                    conflict_data = conflict_envelope.get("data")
                    if not isinstance(conflict_data, dict):
                        raise RuntimeError(
                            f"SQLite lifecycle conflict {raw['conflict_id']} has no signed data object"
                        )
                    signed_projection = {
                        key: value for key, value in conflict_data.items() if key != "integrity"
                    }
                    conflict_digest = hashlib.sha256(rfc8785.dumps(signed_projection)).hexdigest()
                if conflict_digest != raw["payload_sha256"]:
                    raise RuntimeError(
                        f"SQLite conflict digest mismatch for conflict {raw['conflict_id']}"
                    )
                stored = target.execute(
                    """
                    SELECT event_id,payload_sha256,envelope_json,received_at
                    FROM lifecycle_evidence_conflicts WHERE conflict_id=%s
                    """,
                    (raw["conflict_id"],),
                ).fetchone()
                expected_conflict = {
                    "event_id": raw["event_id"],
                    "payload_sha256": raw["payload_sha256"],
                    "envelope_json": raw["envelope_json"],
                    "received_at": raw["received_at"],
                }
                if stored is not None:
                    if any(stored[key] != value for key, value in expected_conflict.items()):
                        raise RuntimeError(
                            f"PostgreSQL conflict identity mismatch for conflict {raw['conflict_id']}"
                        )
                else:
                    target.execute(
                        """
                        INSERT INTO lifecycle_evidence_conflicts(
                            conflict_id,event_id,payload_sha256,envelope_json,received_at
                        ) VALUES (%s,%s,%s,%s,%s)
                        """,
                        (
                            raw["conflict_id"],
                            raw["event_id"],
                            raw["payload_sha256"],
                            raw["envelope_json"],
                            raw["received_at"],
                        ),
                    )
                imported["conflicts"] += 1

            for row in quarantine_rows:
                raw = dict(row)
                target.execute("""
                    INSERT INTO lifecycle_evidence_quarantine(
                        delivery_id,event_id,envelope_json,rejection_reason,received_at
                    ) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(delivery_id) DO NOTHING
                """, (raw["delivery_id"], raw["event_id"], raw["envelope_json"], raw["rejection_reason"], raw["received_at"]))
                stored = target.execute(
                    "SELECT event_id,envelope_json,rejection_reason,received_at FROM lifecycle_evidence_quarantine WHERE delivery_id=%s",
                    (raw["delivery_id"],),
                ).fetchone()
                if (
                    stored is None
                    or stored["event_id"] != raw["event_id"]
                    or stored["envelope_json"] != raw["envelope_json"]
                    or stored["rejection_reason"] != raw["rejection_reason"]
                    or stored["received_at"] != raw["received_at"]
                ):
                    raise RuntimeError(f"PostgreSQL quarantine mismatch for delivery {raw['delivery_id']}")
                imported["quarantine"] += 1

            target.execute("""
                SELECT setval(
                    pg_get_serial_sequence('lifecycle_evidence_conflicts','conflict_id'),
                    GREATEST(COALESCE((SELECT MAX(conflict_id) FROM lifecycle_evidence_conflicts),1),1),
                    true
                )
            """)
            target.execute("""
                INSERT INTO lifecycle_evidence_imports(
                    source_fingerprint,source_path,imported_at,inbox_count,
                    verification_count,conflict_count,quarantine_count
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                fingerprint, str(sqlite_path), datetime.now(UTC),
                imported["inbox"], imported["source_verifications"],
                imported["conflicts"], imported["quarantine"],
            ))
        return {"status": "imported", "source_fingerprint": fingerprint, **imported}
    finally:
        if source is not None:
            source.close()
        Path(snapshot_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", required=True, type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    result = migrate(args.sqlite_path, args.database_url)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
