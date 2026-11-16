# fx-historical-market-analysis-service

Service 2 of the Forex AI platform: a **historical market analysis** service.

Its eventual purpose is to analyse historical foreign-exchange market
observations in order to discover statistically defensible historical
patterns, market regimes, temporal relationships, and other evidence-supported
findings.

> **Status:** Historical analysis, calendar seasonality, forecasting research, and historical replay
> are implemented for research/simulation. Provider selection is explicit and retrieved source-quality evidence is retained.
> Service 1 historical dataset Ed25519 attestations are now verified against an
> out-of-band public-key trust bundle when configured. This authenticates the
> configured Service 1 signer, not the vendor's truth or a vendor signature;
> original historical publication availability remains assumed. Durable research
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
| Historical statistics, patterns, regimes and calendar seasonality | **this service** (research APIs; see limitations) |
| Replay and predictive validation | **this service** (caller records or configured provider retrieval with declared availability assumptions) |
| Authoritative service outputs / lineage | **not integrated** |

This service consumes Service 1's data through a documented contract and does
**not** duplicate any provider, collection, or source-quality logic.

For Railway deployments in the same private network, configure
`UPSTREAM_MARKET_DATA_BASE_URL=http://fx-market-data-service.railway.internal:8000`
(or the actual Service 1 private DNS name and listening port) and set
`UPSTREAM_API_KEY` to the dedicated Service 2 `historical-analysis` key configured in Service 1's `MARKET_DATA_CLIENT_API_KEYS_JSON`; do not reuse Service 1's legacy `API_KEY`. The Service 2
production validator permits plain HTTP only for an explicit-port
`*.railway.internal` origin; public production upstream URLs must use HTTPS.
Do not route private service credentials through browser configuration.

### Historical dataset signature verification

Service 2 now preserves and verifies the optional
`provenance` envelope returned by Service 1's historical-candle endpoint.
Verification uses the shared `indicator-candle-dataset/v1` contract and
Ed25519 public keys provisioned out of band. It checks the exact candle
projection, dataset SHA-256, source ID, provider/instrument/timeframe identity,
price basis, retrieval vintage, source metadata, coverage and quality fields
before a provider-sourced replay can use the dataset.

A successful verification means **the configured Service 1 signing key
attested to this exact normalized dataset**. It does not mean Twelve Data (or
another upstream vendor) digitally signed the prices, prove that the vendor
data is truthful, or establish the first time historical values were publicly
available. Service 2 therefore continues to label historical availability as
`availability_assumed`, derives it from candle close plus the explicit
publication-lag setting, and marks the replay `forecast_eligible=false`.
This is a source-integrity improvement, not a profitability or forecast-skill
claim.

Configure these variables in the Service 2 backend's Railway Variables:

| Variable | Purpose / where to obtain it | Requirement |
|---|---|---|
| `UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` | JSON map from Service 1 signing key ID to base64 raw 32-byte Ed25519 public key. Obtain the public key by running `python scripts/export_historical_attestation_public_key.py` in a trusted Service 1 administrative environment where `MARKET_DATA_CANDLE_ATTESTATION_PRIVATE_KEY_PEM_B64` is available. Verify the printed SHA-256 fingerprint out of band. | Required for production replay; public trust material |
| `UPSTREAM_HISTORICAL_ATTESTATION_REQUIRED` | Set `true` in production. Missing attestations and unknown signing keys then fail closed. | Required true in production |

Example JSON shape (replace both placeholders with the actual key ID and
public key; this is not a usable credential):

```json
{"<service1-key-id>":"<base64-raw-ed25519-public-key>"}
```

Never copy Service 1's private signing key into Service 2, a browser variable,
or a repository. Keep the trusted public key bundle and its fingerprint in
deployment configuration and update it through a reviewed key-rotation
procedure. The root `.env.example` contains placeholders only.

In non-production, missing attestations may be reported as
`service1_attestation_missing` when the requirement flag is false. A present
but malformed, mismatched or incorrectly signed attestation is always rejected;
it is never silently downgraded to unverified data.

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

- **Calendar seasonality research** — descriptive weekday, hour-of-day and month-of-year return/volatility distributions in an explicit IANA timezone, with contiguous-interval filtering, minimum-sample labels and deterministic circular moving-block bootstrap intervals. It does not claim statistical significance or forecast eligibility.
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
- Optional multiclass temperature scaling for direction classification. The
  chronological validation segment is reserved for calibration, only matured
  labels are eligible, and test targets are never used to fit the calibrator.
- Calibration diagnostics include per-fold status, normalized multiclass Brier
  score, log loss and top-label expected calibration error.
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

The API-key-protected-in-production endpoint `POST /api/v1/market-session-liquidity/event-study` accepts caller-supplied, timestamped sweep events and reports the earliest confirmed sweep per `session_instance_id`, grouped by instrument, timeframe and session key. It reports the distribution of minutes from the supplied session open to the first confirmed sweep, directional counts, and post-sweep time-to-displacement, midpoint, consolidation-candidate and invalidation estimates.

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
- Calendar seasonality research by weekday, hour and month with explicit timezone, gap exclusion, sample sufficiency and descriptive uncertainty intervals.
- Forecasting research readiness and experiment execution where the backend permits it.
- Provider-sourced historical rolling-origin replay through Service 1, with optional validated DST-aware session context from Service 61 and explicit publication-lag/provenance caveats.
- Caller-supplied historical replay with optional session and liquidity lifecycle snapshots displayed at each prediction origin.
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


## Production environment variables

This reference follows the current runtime settings and repository environment templates. Required means enforced by production startup validation; conditional entries are only needed when the corresponding integration is enabled. Frontend VITE variables are public build-time configuration and must never contain secrets. Keep all backend credentials and trust material in the deployment secret manager.

| Variable | Purpose / production guidance | Requirement |
|---|---|---|
| `ENVIRONMENT` | Set to production to activate strict security rules. | Required |
| `REQUIRE_AUTH` | Must be true in production. | Required |
| `API_KEY` | At least 32 characters in production. | Required secret |
| `CORS_ALLOW_ORIGINS` | Explicit non-wildcard origins; replace localhost values. | Required |
| `ENABLE_LIVE_TRADING` | Must remain false. | Must be false |
| `SERVICE_MODE` | Must remain `research-simulation`. | Required |
| `SERVICE_NAME` | Service identity. | Optional |
| `SERVICE_VERSION` | Version label. | Optional |
| `API_VERSION` | API version prefix. | Optional |
| `API_HOST` | Bind host. | Optional |
| `API_PORT` | Bind port. | Platform/runtime |
| `LOG_LEVEL` | Logging threshold. | Optional |
| `LOG_FORMAT` | `json` or `console`. | Optional |
| `CORS_ALLOW_CREDENTIALS` | CORS credential policy. | Optional |
| `CORS_ALLOW_METHODS` | Allowed CORS methods. | Optional |
| `CORS_ALLOW_HEADERS` | Allowed CORS headers. | Optional |
| `TRUSTED_HOSTS` | Trusted host allowlist. | Set explicitly |
| `DOCS_ENABLED_IN_PRODUCTION` | Keep false unless approved. | Optional |
| `MAX_REQUEST_BODY_BYTES` | Maximum request body size. | Optional |
| `FORECASTING_ARTIFACT_DIR` | Optional directory for reproducible research artifacts. | Conditional |
| `UPSTREAM_MARKET_DATA_BASE_URL` | Service 1 origin; HTTPS or explicit-port private Railway HTTP in production. | Conditional integration |
| `UPSTREAM_API_KEY` | Service 1 credential; required when upstream market-data URL is configured in production. | Conditional secret |
| `UPSTREAM_FEATURE_ENGINEERING_BASE_URL` | Feature engineering origin; HTTPS or explicit-port private Railway HTTP in production. | Conditional integration |
| `UPSTREAM_FEATURE_ENGINEERING_AUTH_TOKEN` | At least 32 bytes when feature-engineering integration is configured in production. | Conditional secret |
| `UPSTREAM_TIMEOUT_SECONDS` | Overall upstream timeout. | Optional |
| `UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Upstream connect timeout. | Optional |
| `UPSTREAM_READ_TIMEOUT_SECONDS` | Upstream read timeout. | Optional |
| `UPSTREAM_MAX_RETRIES` | Upstream retry count. | Optional |
| `UPSTREAM_RETRY_MAX_DURATION_SECONDS` | Maximum retry duration. | Optional |
| `UPSTREAM_MAX_CONCURRENT_REQUESTS` | Maximum concurrent upstream requests. | Optional |
| `UPSTREAM_MAX_RESPONSE_BYTES` | Maximum decompressed upstream response size. | Optional |
| `UPSTREAM_CONNECTIVITY_CHECK_ENABLED` | Enable readiness connectivity check. | Optional |
| `UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS` | Provider publication-lag assumption required for historical replay when source publish timestamps are unavailable. | Required for market-data replay endpoint |
| `UPSTREAM_MAX_HISTORY_LIMIT` | Maximum permitted historical request limit. | Optional |
| `UPSTREAM_ALLOWED_HISTORY_START` | Optional earliest permitted history timestamp. | Optional |
| `UPSTREAM_ALLOWED_HISTORY_END` | Optional latest permitted history timestamp. | Optional |
| `OTEL_ENABLED` | Enable OpenTelemetry trace export. | Optional |
| `OTEL_ENDPOINT` | OTLP HTTP endpoint. | Conditional |
| `METRICS_ENABLED` | Expose Prometheus metrics. | Optional |
| `DATABASE_URL` | Reserved/unused by current implementation; no database is provisioned. | Do not configure as active persistence |


## GFX Service 9 lifecycle evidence integration — deployment gate

**Status: PROPOSED CONTRACT / NOT ENABLED.** The shared [Liquidity Lifecycle Evidence v1 contract](https://github.com/gavlixdt-tech/fx-api-contracts/tree/main/schemas/liquidity-lifecycle-evidence/v1) is a technical proposal only. It is not an approved Service 9→Service 2 contract, and this repository does not yet automatically ingest authenticated Service 9 lifecycle evidence. The existing caller-supplied event-study endpoint remains research-only and explicitly reports `provenance_status=caller_asserted_unverified` and `forecast_eligible=false`.

Do not add a Service 9 URL, shared API key, caller-provided producer identity, or manually supplied `available_at` to production and treat it as trusted evidence. Before activation, implementation must include Service 9 authenticated workload identity, independently verifiable event signatures, key rotation/revocation, source lineage, immutable first-availability timestamps, instrument/timeframe/price-basis compatibility, durable deduplication, bounded replay, and leakage tests. A valid JSON Schema or successful HTTP request is not provenance verification.

### Deployment instructions for this boundary

No new environment variable is currently required or supported for this proposed integration. Do not invent or configure one. When the boundary is approved and implemented, obtain the Service 9 backend origin from Railway → GFX project → `fx-liquidity-analysis-service` → Networking; use its private `.railway.internal` address for same-project backend traffic. Any future trust bundle must be distributed through Railway backend Variables/secret management from an authority-approved public-key registry; private signing keys must remain only with the producer/key custodian. The exact variable names and provisioning steps must be added here before enabling the integration.
