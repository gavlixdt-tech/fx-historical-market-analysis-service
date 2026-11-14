# fx-historical-market-analysis-service

Service 2 of the Forex AI platform: a **historical market analysis** service.

Its eventual purpose is to analyse historical foreign-exchange market
observations in order to discover statistically defensible historical
patterns, market regimes, temporal relationships, and other evidence-supported
findings.

> **Status:** Historical analysis, forecasting research, and historical replay
> are implemented for research/simulation. Provider selection is explicit and
> retrieved source-quality evidence is retained, but source entitlement and
> historical availability are not independently verified. Durable research
> artifacts and production workload identity are not integrated. See the
> [current integration audit](docs/integration/service2-ecosystem-integration-audit.md)
> and [acceptance report](docs/acceptance/service2-integration-acceptance-report.md).
> No live prediction, signal, trading, or production model serving is provided.

Private research system. Research / simulation mode only.

---

## Relationship to `fx-market-data-service`

This service is a **separate, independently deployable repository**. It is not
part of the Service 1 repository, the desktop application, or any other
microservice's directory.

| Concern | Owner |
| --- | --- |
| Provider integration, provider credentials | `fx-market-data-service` |
| Quote normalisation and validation | `fx-market-data-service` |
| Feed management and collection | `fx-market-data-service` |
| Provenance, freshness, source quality | `fx-market-data-service` |
| Historical dataset requests | **this service** (via the upstream contract) |
| Analytical input validation | **this service** (rejects unsuitable input) |
| Historical statistics and patterns | **this service** (research APIs; see limitations) |
| Replay and predictive validation | **this service** (caller records or configured provider retrieval with declared availability assumptions) |
| Authoritative service outputs / lineage | **not integrated** |

This service consumes Service 1's data through a documented contract and does
**not** duplicate any provider, collection, or source-quality logic.

For Railway deployments in the same private network, configure
`UPSTREAM_MARKET_DATA_BASE_URL=http://fx-market-data-service.railway.internal:8000`
(or the actual Service 1 private DNS name and listening port) and set
`UPSTREAM_API_KEY` to the same secret as Service 1's `API_KEY`. The Service 2
production validator permits plain HTTP only for an explicit-port
`*.railway.internal` origin; public production upstream URLs must use HTTPS.
Do not route private service credentials through browser configuration.

### Historical session-context integration

For point-in-time historical session features, configure
`UPSTREAM_FEATURE_ENGINEERING_BASE_URL` to the feature-engineering service
origin. If that service has `AUTH_TOKEN` configured, set the matching
`UPSTREAM_FEATURE_ENGINEERING_AUTH_TOKEN` in this service. The URL is
server-side only and must not contain a path or credentials.

When configured, market-data replay requests DST-aware session context from
`POST /api/v1/session-context` in batches of at most 1,000 candle-close
timestamps. The consumer validates the v1 contract, response count, and exact
timestamp alignment before attaching a context to each replay observation.
Calendar context is deterministic from the timestamp and is marked available
at candle close; it is not evidence of order flow or provider-sourced market
activity. A configured but unavailable or contract-invalid dependency blocks
the provider replay instead of silently omitting the feature. If the URL is
not configured, the replay remains explicitly marked as missing session
features and returns a warning.

---

## Implemented in this phase

- **Backend** — FastAPI application factory, validated configuration, versioned
  routing under `/api/v1`, request correlation IDs, consistent error
  envelopes, structured JSON logging, Prometheus metrics, optional
  OpenTelemetry tracing, health/readiness/status/version endpoints, and a
  typed read-only upstream client.
- **Provider-sourced replay** — optional replay route reads complete historical
  candles from a configured real provider through Service 1, requires an explicit
  publication-lag assumption, and records the source/coverage/availability policy
  in the replay fingerprint report. Provider identity is checked, but production
  use is blocked pending approved Service 64 identity and the Service 1 auth
  contract. It is not a continuous live feed.
- **Provider selection** — historical retrieval requires an explicit configured
  provider with historical-candle capability; real providers are connection-tested.
  No default test provider or synthetic fallback is used.
- **Frontend** — a dedicated React + TypeScript + Vite dashboard with a typed
  API client, runtime response validation, and accurate loading, empty,
  unavailable, and error states.
- **Operations** — Dockerfiles for both artefacts, a Compose stack, CI for
  tests, linting, type checking, builds, and container checks, and an
  `.env.example` containing placeholders only.

## Forecasting readiness (Prompt 5)

- Typed forecasting-problem specifications, prediction targets, point-in-time features.
- Deterministic future-outcome labels, chronological splits, purge and embargo.
- Dataset manifests, quality reports, and baseline evaluation metrics.
- No model training, inference, signals, or trading capabilities.

## AI forecast research & evaluation (Prompt 6)

- Pure-Python model portfolio: baselines, ridge regression/logistic, random forest,
  histogram gradient boosting.
- Leakage-resistant walk-forward evaluation with purge/embargo and holdout isolation.
- Target-appropriate metrics, fold-level stability, block bootstrap uncertainty.
- In-memory experiment store with optional local JSON artifacts (configurable).
- API endpoints under `/api/v1/forecasting` for model families, experiment validation,
  execution, retrieval, folds, comparison and limitations.
- Integrated frontend workspace for experiment configuration and results.
- No live prediction, signals, trading, or production model serving.

## Historical replay and predictive robustness (Phase 4.5)

- Chronological rolling-origin replay with explicit `available_at` timestamps.
- Expanding/rolling training windows, target-maturity purging, and optional
  embargo; preprocessing is fitted only on each origin's training data.
- Baselines, out-of-sample prediction records, class-wise calibration
  diagnostics, causal heuristic-regime slices, and model-family comparisons.
- Supplementary block-bootstrap White's Reality Check approximation and
  combinatorial Probability of Backtest Overfitting diagnostic.
- Dataset fingerprints and replay configuration are returned for
  reproducibility; historical source availability is caller-asserted and
  results are not persisted.
- The dedicated workbench accepts a caller's JSON dataset; it does not create
  demo historical observations.

See [docs/historical-replay.md](docs/historical-replay.md) for the contract and
limits. GFX service-output ingestion, service ablations, signed provenance,
durable replay artifacts, and a verifiably untouched future evaluation remain
outside this implementation. No profitability or production-readiness claim is
made.


## Session-conditioned liquidity event study (research only)

The authenticated endpoint `POST /api/v1/market-session-liquidity/event-study` accepts caller-supplied, timestamped sweep events and reports the earliest confirmed sweep per `session_instance_id`, grouped by instrument, timeframe and session key. It reports the distribution of minutes from the supplied session open to the first confirmed sweep, directional counts, and post-sweep time-to-displacement, midpoint, consolidation-candidate and invalidation estimates.

Post-sweep transition timing uses Kaplan-Meier estimates with right-censored observations. The request's `analysis_cutoff` excludes records not yet available at that cutoff and truncates follow-up at the cutoff; the endpoint never treats a not-yet-observed transition as a confirmed failure. The default minimum group size is 30 for a descriptive-sufficiency label; smaller groups remain visible but are explicitly marked insufficient.

The dashboard includes a view-only event-study workspace that accepts a caller-supplied JSON payload and renders the returned group summaries. It does not automatically ingest Service 18 events, independently authenticate event producers, persist event-study datasets, or feed the model-training/forecasting pipeline. Event completeness, session identity, source timestamps and availability are caller-asserted. It is descriptive research, not a forward forecast, BUY/SELL instruction, proof of resting stop orders, or evidence of profitability. Do not use its distributions as model features until producer provenance, instrument-specific historical coverage, leakage-resistant walk-forward validation, multiple-testing controls and independent calibration are established.

---

## Dashboard workspaces

The React dashboard provides:

- Service overview, readiness and safe operational diagnostics.
- Historical provider inventory and explicit provider selection.
- Bounded historical retrieval with an OHLC candlestick chart and recent candle table.
- Dataset quality and provenance details from the actual retrieval response.
- Retrospective regime and pattern research through the existing analysis API.
- Forecasting research readiness and experiment execution where the backend permits it.
- Historical rolling-origin replay, including caller-supplied session and liquidity lifecycle context at each prediction origin.
- A view-only session/liquidity event-study workspace for caller-supplied event JSON.

Session and lifecycle replay context remains caller-asserted and unverified. Experiment and replay results remain in-memory unless an explicitly documented artifact mechanism is configured; this repository does not claim a durable experiment-history registry.

The dashboard does not execute trades, publish BUY/SELL signals, or approve downstream trading decisions.

---

## Quick start

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Dashboard | <http://localhost:8080> |
| Backend API | <http://localhost:8000/api/v1> |
| API docs | <http://localhost:8000/docs> |

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` if the backend is not on the same origin.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | System context, module responsibilities, boundaries, diagrams. |
| [`docs/api.md`](docs/api.md) | Endpoint reference, envelopes, error codes, auth. |
| [`docs/historical-replay.md`](docs/historical-replay.md) | Point-in-time replay contract, methodology, reproducibility, and limits. |
| [`docs/security.md`](docs/security.md) | Implemented controls, secret handling, known limitations. |
| [`docs/development.md`](docs/development.md) | Local setup, checks, how to extend. |
| [`docs/deployment.md`](docs/deployment.md) | Images, production configuration, probes, rollback. |
| [`docs/acceptance-audit.md`](docs/acceptance-audit.md) | Acceptance criteria, evidence, blocked items. |
| [`docs/integration/service2-ecosystem-integration-audit.md`](docs/integration/service2-ecosystem-integration-audit.md) | Current dependency status and integration boundaries. |
| [`docs/operations/production-readiness.md`](docs/operations/production-readiness.md) | Current production gates and blockers. |
| [`docs/operations/recovery-runbook.md`](docs/operations/recovery-runbook.md) | Recovery limitations and safe restart procedure. |
| [`docs/testing/integration-verification.md`](docs/testing/integration-verification.md) | Local-test versus live-integration evidence. |
| [`docs/acceptance/service2-integration-acceptance-report.md`](docs/acceptance/service2-integration-acceptance-report.md) | Current Service 2 acceptance matrix. |
| [`contracts/upstream-market-data-contract.md`](contracts/upstream-market-data-contract.md) | The verified Service 1 contract and the unverified parts. |

---

## Upstream contract status

| Item | Status |
| --- | --- |
| Service 1 request paths and query parameters | **VERIFIED** (read from the Service 1 source) |
| Service 1 response envelopes and payload fields | **VERIFIED** |
| Service 1 error format and status codes | **VERIFIED** |
| Service 1 correlation / trace headers | **VERIFIED** |
| Service 1 authentication header and API-key middleware | **VERIFIED IN SOURCE** (`X-API-Key`) |
| Platform API Gateway Service 1 route and dedicated credential injection | **VERIFIED IN SOURCE** |
| Production workload identity, deployed secret parity, and per-service authorization | **NOT YET VERIFIED** |

Service 1's static OpenAPI file remains a placeholder without a security
scheme. Its current source implements constant-time `X-API-Key` validation,
and the Gateway injects the dedicated `MARKET_DATA_API_KEY` server-side.
This verifies the source-level credential contract, not deployed workload
identity, secret parity, rotation, or per-service authorization. The
pre-production checklist is in
`contracts/upstream-market-data-contract.md` section 5.

---

## Repository publication

Before any commit or push, inspect the current branch, remote, and working-tree
changes. A local implementation or passing test suite is not evidence that a
change was pushed or deployed.

---

## License

Private. All rights reserved by the platform owner.
