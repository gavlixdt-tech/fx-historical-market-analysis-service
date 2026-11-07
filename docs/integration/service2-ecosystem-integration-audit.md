# Service 2 ecosystem integration audit

**Assessment:** BLOCKED for production integration; local research/simulation
features are implemented. This audit supersedes older foundation-phase
statements in this repository's acceptance documents.

Service 2 owns historical analysis, research configuration, and replay
calculations. It does not own provider access, reusable platform features,
durable canonical storage, decisions, or trade execution. A configured URL or
local fixture is not evidence that a dependency is operational.

| Dependency | Direction / ownership | Current implementation | Classification | Remaining blocker |
|---|---|---|---|---|
| Service 1 `fx-market-data-service` | Service 2 reads historical candles; Service 1 owns providers and source quality | Typed read-only client, explicit provider inventory/selection, capability and configuration checks, provider connection test, bounded retrieval, source-quality metadata checks | PARTIALLY_IMPLEMENTED | Production authentication and approved Service 64 identity are unverified; real provider entitlement and live history were not verified in this assessment; historical first-available time is absent |
| Service 60 `fx-data-storage-service` | Service 2 writes research manifests/results; Service 60 owns canonical storage | No Service 2 client or artifact write/read path | BLOCKED | Verified envelope cannot attest the required producer/source lineage; no approved artifact contract or workload grant |
| Service 61 `fx-feature-engineering-service` | Service 2 may request shared feature definitions | Service 2 retains its own point-in-time feature builder; no Service 61 call | PARTIALLY_IMPLEMENTED | Shared feature names/formulas and point-in-time cutoff/fit lineage are not contract-compatible and approved |
| Service 63 `fx-decision-orchestrator-service` | Service 63 calls Service 2 for historical research only | Matching versioned route names exist; request/response were cross-checked against the current Service 63 client models | IMPLEMENTED_NOT_VERIFIED | No authenticated Service 63 → Service 2 runtime test; production workload authorization is unavailable; historical results remain non-decision evidence |
| Service 21 `fx-statistical-forecast-service` | Potential bounded historical data handoff | No handoff client | BLOCKED | Fitted forecast and robustness operations are not implemented; no accepted dataset/lineage contract |
| Service 49 `fx-backtesting-service` | Potential immutable dataset handoff; Service 49 owns backtest evaluation | No handoff client | NOT_IMPLEMENTED | No compatible dataset-reference contract or independent validation run |
| Service 50 `fx-walk-forward-validation-service` | Potential immutable dataset handoff; Service 50 owns walk-forward validation | No handoff client | NOT_IMPLEMENTED | No compatible dataset-reference contract or independent validation run |
| Service 62 `fx-event-bus-service` / event schemas | Lifecycle events only where a real consumer requires them | No Service 2 publisher; the inspected local transport is not production broker evidence | BLOCKED | No approved production transport, topic/schema registration, publisher identity, or consumer acknowledgement |
| Service 64 `fx-security-access-service` | Inbound/outbound workload identity | Local inbound API-key middleware only; no approved Service 2 workload grant | BLOCKED | Issuer, audience, scopes, and production grants are unavailable; shared keys are not treated as workload identity |
| Service 65 `fx-observability-service` | Central metrics/traces/logs | Local Prometheus metrics and optional OpenTelemetry instrumentation | PARTIALLY_IMPLEMENTED | Central endpoint, authentication, trace propagation, and ingestion were not verified |
| Service 66 `fx-disaster-recovery-service` | Backup and restore of durable Service 2 artifacts | No durable Service 2 artifact store or recovery integration | BLOCKED | No approved backup contract or tested restore |

## Verified Service 2 behavior

- Historical data retrieval requires an explicit provider ID. The client
  verifies that the provider is registered, configured, and advertises
  historical-candle support. Real providers are connection-tested before use.
- Test providers are accepted only in development/testing and are labelled
  synthetic. Provider-sourced replay rejects test providers.
- Instrument identifiers are checked against Service 1's
  `surveillance-instruments/1` scope. Provider replay uses canonical
  slash-delimited identifiers and supported timeframes.
- Retrieval has explicit timeouts, retries, a concurrency bound, response-size
  limits, origin-only URL validation, and redirects disabled.
- Provider replay records `availability_provenance=availability_assumed`.
  The derived `available_at` is close time plus a configured lag; it is not
  provider-verified availability.
- Caller-supplied experiment provenance labels are recorded as declarations,
  not accepted as proof. Caller-supplied experiment data remains
  `user_supplied_unverified`.
- Synthetic generic replay/experiment fixtures are rejected in production
  when the request explicitly declares them synthetic. No fallback data is
  generated.
- Trading, order, and broker-execution APIs are not part of this service.

## Dependency direction

`Browser → Service 2 → Service 1` is the only implemented provider-data path.
Service 63 may call Service 2's research replay routes. Service 2 does not call
Services 60, 61, 21, 49, 50, or 62. No circular service dependency is
introduced.

## Evidence boundary

This is a source and local-test audit, not a production deployment test. A
provider listing, a successful local fixture, a configured endpoint, or a
matching route name does not prove provider entitlement, workload
authorization, cross-service reachability, central telemetry, durability, or
recovery.
