# Service 2 integration acceptance report

## Executive result

**BLOCKED for production integration; PASS WITH EXPLICIT LIMITATIONS for the
local research/simulation implementation.** No real-provider entitlement,
production Service 64 identity, Service 60 persistence, central
observability, disaster recovery, or deployed end-to-end integration is
claimed.

## Acceptance matrix

| Area | Result | Evidence / limitation |
|---|---|---|
| Existing implementation | PASS WITH EXPLICIT LIMITATIONS | Existing analysis, forecasting research, and replay preserved |
| Service 1 contract | PASS WITH EXPLICIT LIMITATIONS | Typed response now preserves and verifies the Service 1 Ed25519 historical dataset attestation against out-of-band keys; runtime provider/auth verification remains outstanding |
| Provider selection | PASS WITH EXPLICIT LIMITATIONS | Explicit provider, type/config/capability checks, connection test; no real entitlement verified |
| Historical quality | PASS WITH EXPLICIT LIMITATIONS | Coverage and validation evidence preserved; producer remains authority |
| Availability provenance | BLOCKED | Close-plus-lag is an assumption; no original first-available timestamp |
| Replay integrity | PASS WITH EXPLICIT LIMITATIONS | UTC, chronology, OHLC, future-time, availability and sample-bound checks; revisions/signatures absent |
| Service 60 | BLOCKED | No adapter; no approved artifact envelope |
| Service 61 | BLOCKED | No equivalent point-in-time shared feature contract |
| Service 63 | BLOCKED | Source schema check only; no authorized runtime handoff |
| Services 21/49/50 | BLOCKED / NOT_IMPLEMENTED | No compatible data handoff; fitted Service 21 endpoint unavailable |
| Service 62 | BLOCKED | No production publisher/topic/consumer acknowledgement |
| Service 64 | BLOCKED | Approved workload identity/grant absent |
| Service 65 | PASS WITH EXPLICIT LIMITATIONS | Local metrics/tracing only; central ingestion unverified |
| Service 66 | BLOCKED | No durable integration or tested restore |
| Frontend | PASS WITH EXPLICIT LIMITATIONS | Historical OHLC chart/table, dataset quality/provenance, retrospective regime/pattern research, replay context display, and caller-supplied event-study view are integrated; durable experiment history and automatic Service 18 event ingestion remain unavailable |
| Production/deployment | BLOCKED | No production identity, live provider, recovery, or deployed verification |
| Trading/order execution | NOT_APPLICABLE | This service does not place orders or trade |

## Verification run

| Check | Result |
|---|---|
| Backend regression suite | **PASS** — 136 passed, 1 skipped, 1 deprecation warning (`pytest tests -q`, run from `backend/`) |
| Ruff lint | **PASS** — `ruff check app tests` |
| Ruff format | **PASS** — `ruff format --check app tests` (83 files checked) |
| Mypy | **PASS** — `mypy app` (53 source files) |
| Frontend tests | **PASS** — 23 passed across 4 test files |
| Frontend type-check | **PASS** — TypeScript `tsc --noEmit` |
| Frontend production build | **PASS** — Vite production build |
| OpenAPI generation | **PASS** — 28 paths generated; provider inventory and provider-sourced replay routes present |
| Live provider / cross-service runtime | **NOT VERIFIED** — no provider entitlement or authorized production identity was available |
| Container image builds | **NOT VERIFIED** — Docker builds were started, but base-image/package downloads remained in progress at very low throughput and were stopped; no build failure was observed |
| CI, performance, deployment, restore | **NOT VERIFIED** — local source checks do not prove these gates |

Contract fixtures are synthetic and do not count as live integration evidence.

## Repository scope

Only the primary Service 2 repository is modified by this implementation.
Supporting repositories were inspected read-only. Pre-existing unrelated
worktree changes must remain separate from any Service 2 commit.


## 2026-11-14 dashboard and integration implementation addendum

The following changes were committed directly to `master` after the earlier acceptance snapshot:

- Added a historical OHLC candlestick chart and recent-candle table driven by the retrieved dataset response.
- Added a dataset quality/provenance panel that consumes the actual retrieval response and does not assume a separate `/provenance` endpoint.
- Replaced the reserved historical analysis workspace with a form backed by the existing `POST /api/v1/analysis/research-summary` endpoint.
- Added a provider-sourced replay workspace backed by `POST /api/v1/historical-replay/run-from-market-data`, which invokes the existing server-side Service 1 retrieval and optional Service 61 session-context integration.
- Added a view-only session/liquidity event-study workspace backed by `POST /api/v1/market-session-liquidity/event-study`, accepting caller-supplied JSON and rendering group statistics and Kaplan-Meier survival curves.
- Extended the frontend replay schemas to retain the existing session-context and liquidity-lifecycle fields and display market context at prediction origins.
- Added dashboard section navigation and focused tests for the provenance and OHLC views.
- Changed dependency audit steps so Python and npm vulnerability scan failures are no longer suppressed.

**Verification boundary:** the pre-existing test counts in this report predate these 2026-11-14 commits. The current changes were committed through the GitHub integration, but no local frontend/backend test or production build was executed during this repository session. The latest commit's combined GitHub status response contained no status entries, and the available workflow-run lookup did not return push-triggered runs. Therefore, the new implementation is **committed but CI-unverified** until the repository's push-triggered workflow completes.

**External integration limitations remain:** Service 61 session context is optional and depends on its configured contract and credentials; Service 18 event ingestion is not automatic; provider identity and original historical publication time are not independently authenticated by the current Service 1 contract; experiment/replay results are not a durable history registry. These must not be described as complete production integrations.



## 2026-11-17 historical source-attestation implementation addendum

The following code changes were committed directly to `master`:

- Added the Service 1 `provenance` and `canonical_record_reference` fields to the typed historical response model, including the complete coverage metadata field `max_consecutive_missing_intervals`.
- Added a purpose-specific Ed25519 verifier for the shared `indicator-candle-dataset/v1` contract. It checks signer key ID, signature, exact canonical candle projection and SHA-256, source ID, provider/instrument/timeframe identity, retrieval vintage, price basis, source metadata, coverage and validation quality.
- Wired verification into provider-sourced replay after the returned provider/instrument/timeframe/price-basis identity is matched to the request and before replay observations are constructed.
- Production configuration with Service 1 enabled now requires `UPSTREAM_HISTORICAL_ATTESTATION_REQUIRED=true` and a non-empty out-of-band `UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` trust bundle. Unknown keys, missing attestations and invalid signatures fail closed.
- Added the `cryptography` runtime dependency, environment template entries, a documented Service 1 public-key export procedure, and tests for valid signatures, tampering, unknown keys, missing attestations, metadata mismatch and production configuration.
- Added the explicit `vendor_defined` price-basis enum and request/UI option so Service 2 can represent Service 1's actual provider-defined price basis without mislabelling it as midpoint.

**Evidence boundary:** this signature authenticates the configured Service 1 signer and the exact dataset/quality projection. It does not prove the vendor digitally signed the prices, prove upstream source truth, or supply the original first-available timestamp. Replay availability therefore remains `availability_assumed` (candle close plus a configured lag), and replay outputs are explicitly marked `forecast_eligible=false` and `trading_authorization=false`.

**Initial verification boundary (superseded by the CI evidence below):** at the time this addendum was first written, the verifier and configuration tests had been added but had not yet run. The subsequent CI run below provides code-level verification; it does not establish provider entitlement, production identity, vendor authenticity, or deployed replay acceptance.



## 2026-11-17 Service 2 historical attestation and operator-settings implementation

The following additional implementation is now committed to `master`:

- Service 1 historical dataset attestation is preserved by the typed Service 2 client and verified with an out-of-band Ed25519 trust bundle. Verification binds the exact normalized OHLCV projection and source-quality metadata. It does not claim a vendor signature, vendor truth, or historical first-available timestamp.
- Service 2 has a dedicated Admin Console settings client. It obtains a short-lived Service 64 workload token, validates the token response, polls unacknowledged pending versions, verifies canonical SHA-256 digests, validates the six replay controls, and submits exact-version READY/REJECTED acknowledgements.
- Admin Console pending-version retrieval now excludes versions already acknowledged by the same consumer with the same content digest and has a bounded 1,000-version backlog. This prevents repeated processing of acknowledged versions and ensures rejected candidates do not permanently block later valid candidates.
- The active effective settings snapshot is digest-verified before use. The client is fail-closed whenever central settings are enabled; a rejected pending candidate is recorded in replay reproducibility metadata while the last active valid snapshot remains in use.
- Added bounded, versioned Admin Console controls for lookback, minimum training samples, expanding/rolling validation, rolling window, embargo periods and random seed, with cross-field validation.
- Added deployment instructions and variable ownership to the Service 2, Admin Console and Service 64 main READMEs. The Service 2 identity requires only `gfx:settings:read` and `gfx:settings:ack`.

**CI evidence:** GitHub Actions run `43978565479` for commit
`6c7678202b8ff5f2ddb8cf1adaa77dd8a641624c` completed successfully for backend
lint, formatting, mypy and tests; frontend tests/type-check/build; container
build/smoke checks; and dependency/secret audit.

**Not yet accepted in production:** the Service 2 workload identity and Admin
Console consumer must still be created in the deployed Service 64/Admin Console,
Railway backend origins and credentials provisioned, and a real cross-service
request/acknowledgement/active-settings replay performed. This code-level CI
result is not a live-provider or deployment acceptance result.



## 2026-11-17 active settings layer provenance addendum

The Service 2 settings integration now records more than the final effective
snapshot digest. The Admin Console active endpoint returns the active version
ID and content digest for every existing inherited layer (global, instrument,
timeframe and instrument-timeframe). Service 2 validates the layer list,
scope IDs, ordering, version ID consistency and SHA-256 syntax, then persists
the layer provenance in replay reproducibility metadata. Admin Console verifies
each layer's stored content digest before returning it.

**Latest strict CI evidence:** run `43979721402` for commit
`5e350f9212b7460eaf3ca43eff4855e8e8b965ce` completed successfully, including
the strict `ruff format --check`, lint, mypy, all backend tests, frontend
checks/build, container build/smoke test, and dependency/secret audit.

The Admin Console repository includes tests for the new pending-acknowledgement
deduplication and active-layer response, but its GitHub Actions jobs have been
failing before runner assignment (empty runner name and no executed steps).
Those tests therefore remain unverified by CI; this is a GitHub Actions
execution/runner availability blocker, not a passing test result.
