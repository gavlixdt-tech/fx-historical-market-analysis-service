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
| Service 1 contract | PASS WITH EXPLICIT LIMITATIONS | Route/schema source cross-check and synthetic fixtures; auth unverified |
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
