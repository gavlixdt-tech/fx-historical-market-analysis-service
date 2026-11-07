# Service 60 artifact persistence boundary

## Current state

Service 2 does not currently have a typed Service 60 client, durable dataset
manifest API, research-artifact write/read path, or persistence-backed
history view. Forecasting experiments are held in process memory; an optional
local JSON artifact path is not a canonical, replicated, or recoverable
artifact store.

The audited Service 60 API includes record creation and retrieval/list
operations with authentication and idempotency, but Service 60 preserves
producer-supplied provenance; it does not independently attest source
identity, payload hashes, timestamps, or producer authorization. Its current
record envelope does not establish all the research lineage Service 2 needs.

## Decision

No persistence adapter or schema change is implemented. Writing the current
research result into the existing envelope would imply stronger lineage and
integrity than the contract proves. No Service 60 database schema has been
changed.

## Required contract before implementation

An approved versioned artifact contract must define dataset and result
identity, source-record references, instrument/timeframe/price basis,
availability provenance, analysis cutoff, parameters and algorithm/feature/
model versions, seed, code and commit identity, results, warnings, and
limitations. It must also define authentication, TLS, idempotency, immutable
identity, bounded payloads, and retrieval semantics.

Until that contract and an authorized workload grant exist, persistence
status must remain unavailable; failed or unattempted writes must never be
reported as successful.
