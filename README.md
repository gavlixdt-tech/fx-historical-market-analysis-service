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
| **Service 1 authentication mechanism** | **PROPOSED — NOT YET VERIFIED** |
| Platform API gateway routes | **PROPOSED — NOT YET VERIFIED** |

Service 1's OpenAPI document is a placeholder with no security schemes, and its
production middleware comes from an unvendored shared package. A shared static
API key is therefore **not** assumed to be the correct production design. The
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
