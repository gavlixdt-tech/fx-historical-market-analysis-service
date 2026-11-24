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
> artifacts are not yet persisted. The Service 2-to-Service 64 workload identity
> and Admin Console settings consumer client are implemented but require deployment
> registration, secrets, and runtime acceptance. See the
> [current integration audit](docs/integration/service2-ecosystem-integration-audit.md)
> and [acceptance report](docs/acceptance/service2-integration-acceptance-report.md).
> No live prediction, signal, trading, or production model serving is provided.

Private research system. Research / simulation mode only.

---

## Causal market-structure analysis

The versioned API now exposes `POST /api/v1/analysis/market-structure`.
It accepts a chronologically ordered OHLC history and returns timestamped,
causally-confirmed structural observations including swing highs/lows,
breaks of structure (BOS), changes of character (CHoCH), buy-/sell-side
liquidity sweeps, volatility-scaled equal-high/low pools, displacement,
three-candle fair-value gaps, engulfing/rejection candle anatomy, order-block
*proxies*, and volatility/range context.

Example request:

```json
{
  "instrument": "EUR/USD",
  "timeframe": "H1",
  "observations": [
    {"timestamp":"2026-01-01T00:00:00Z","open":1.1,"high":1.102,"low":1.099,"close":1.101}
  ],
  "config": {"pivot_left":3,"pivot_right":3,"atr_window":14}
}
```

The request above is illustrative only; at least 20 chronologically ordered
observations are required. The endpoint is bounded to 5,000 observations per
request. Long histories must be paginated/replayed in chronological windows
with sufficient overlap; do not concatenate duplicate candles or let future
bars enter a past decision. Confirmed pivots are timestamped when confirmation
becomes available, not when the pivot first formed. This avoids look-ahead
bias in replay.

Input integrity is enforced before structural calculations: OHLC values must be
finite and positive, observations must be strictly chronological, timestamps
must include an explicit timezone, and optional volume must be finite and
non-negative. Missing volume remains valid and is represented as unavailable;
it is never silently replaced with zero. Invalid observations fail the request
rather than being silently dropped or repaired. Regression coverage includes
NaN/infinite/negative volume and timezone-naive timestamps.

This endpoint is an OHLC structure extractor, not a trained forecasting model,
not an order-book reconstruction, and not a trade authorization service.
OHLC cannot reveal actual dealer inventory, participant identity, or complete
bid/ask depth. Order blocks are explicitly labelled proxies. Event strength
is a bounded heuristic score, not a probability of profit. Forecasting must
combine these features with independently validated models, calibrated
uncertainty, transaction costs and risk authorization.

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

### Central Admin Console settings integration (Service 2 → Service 64 → Admin Console)

Service 2 can now resolve the approved effective replay settings for each
instrument/timeframe scope. It obtains a short-lived workload token from
Service 64, calls the Admin Console's authenticated
`GET /api/v1/settings/consumer/active` endpoint, verifies the returned
canonical SHA-256 snapshot digest, validates all six replay controls, and
records the effective settings digest and every contributing global,
instrument, timeframe and instrument-timeframe version in replay
reproducibility metadata. The Admin Console resolves these layers using its
existing versioned/approved settings control plane.

**Fail-closed behavior:** when `GFX_SETTINGS_ENABLED=true`, the
`GFX_SETTINGS_REQUIRED=true` flag is mandatory. Authentication failures,
missing consumer registration, unavailable services, invalid active settings,
unsupported scopes, and active/candidate digest mismatches block the replay.
A well-formed but out-of-bounds pending candidate is acknowledged as
`REJECTED`, recorded in replay metadata, and cannot be activated; the last
active valid snapshot remains usable. Service 2 never silently falls back to
caller-supplied tuning parameters after central settings have been enabled. With the integration disabled, the existing request-level
research controls remain available.

**Settings available in the Admin Console** (bounded and cross-validated):

| Setting key | Default | Allowed range / choices | Effect |
|---|---:|---|---|
| `historical_replay.lookback` | 20 | 2–200 bars | Feature lookback for replay origins |
| `historical_replay.min_train_samples` | 30 | 10–1,000 observations | Minimum training sample count |
| `historical_replay.validation_mode` | expanding | expanding / rolling | Chronological training-window policy |
| `historical_replay.rolling_window` | 250 | 10–1,500 observations | Rolling window; must be at least min_train_samples |
| `historical_replay.embargo_periods` | 1 | 0–500 bars | Additional temporal separation between train and test |
| `historical_replay.random_seed` | 42 | 0–2,147,483,647 | Reproducibility for stochastic model families |

These settings affect research replay only. They do not change the target,
prediction horizon, source data, or model-family allowlist, and they do not
authorize live signals or trading. Settings changes should be versioned,
reviewed, approved and activated in the Admin Console; do not edit values
directly in the Service 2 environment.

#### One-time deployment setup

1. **Create a dedicated Service 2 workload identity in Service 64.** Use a
   Server Admin account and call `POST /api/v1/service-identities` on the
   Service 64 backend. The request body is:

   ```json
   {
     "service_number": 2,
     "name": "fx-historical-market-analysis-service",
     "scopes": ["gfx:settings:read", "gfx:settings:ack"]
   }
   ```

   The Server Admin bearer token is required. Save the returned `id`,
   `client_id`, and `client_secret` immediately; the secret is displayed
   once. Do not reuse a human JWT, API key, or another service's credentials.

2. **Register Service 2 as a consumer in the Admin Console.** Call
   `POST /api/v1/settings/consumers` on the Admin Console backend using a
   Server Admin bearer token. Use the exact identity `id` returned by Service
   64:

   ```json
   {
     "identity_id": "<service64-identity-id>",
     "service_number": 2,
     "name": "fx-historical-market-analysis-service",
     "scope_types": ["global", "instrument", "timeframe", "instrument_timeframe"],
     "required": true
   }
   ```

   The Admin Console verifies the identity against Service 64 before
   registration. Confirm it appears in `GET /api/v1/settings/consumers` with
   `enabled=true`, `required=true`, and all four scope types. Service 2
   validates pending candidates and posts version-bound READY/REJECTED
   acknowledgements before reading the active effective snapshot. Do not
   create a second identity for the same service number.

3. **Configure the Service 2 backend Railway Variables.** These are backend
   variables only; never put them in Vercel `VITE_*` variables or browser
   code.

| Variable | Value / where to get it | Secret? |
|---|---|---|
| `GFX_SETTINGS_ENABLED` | `true` after steps 1–2 are complete | No |
| `GFX_SETTINGS_REQUIRED` | `true`; required whenever the integration is enabled | No |
| `GFX_SETTINGS_SERVICE_URL` | Admin Console backend origin. Prefer `http://<admin-console-railway-service>.railway.internal:<port>`; obtain the exact Railway private domain and listening port from that service's Railway Networking/Variables settings. Public fallback must be HTTPS. | No |
| `FX_SECURITY_SERVICE_URL` | Service 64 backend origin, preferably its Railway private domain and explicit port; public fallback must be HTTPS. Obtain it from the Service 64 Railway service settings. | No |
| `GFX_SETTINGS_CLIENT_ID` | Client ID returned by Service 64 when creating the Service 2 workload identity | Sensitive identifier |
| `GFX_SETTINGS_CLIENT_SECRET` | One-time secret returned by Service 64; rotate through Service 64 if lost | **Yes** |

4. Deploy Service 2 and verify that it can reach Service 64 and the Admin
   Console over the configured private network. Then activate a settings
   version in the Admin Console and run a provider-sourced historical replay.
   Confirm the response's `reproducibility.operational_settings.source` is
   `admin_console`, the expected scope/version/digest are present, and
   changing a scoped value changes the replay's effective parameters.
   A missing or invalid dependency must return a dependency error, not fall
   back to request settings.

**Current implementation boundary:** the client, workload-token exchange, pending-version validation and
acknowledgement, scoped resolution, digest validation, bounded parameter
model, fail-closed configuration and unit tests are committed. The live identity creation,
Admin Console consumer registration, Railway URL/secret provisioning and
runtime test require access to the actual deployment and authorized admin
credentials. This repository edit does not claim those external steps have
already happened. Run the Service 2 unit suite and deployment acceptance
workflow before treating the connection as accepted.

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
  in the replay fingerprint report. Provider identity is checked and the optional Service 1 dataset attestation
  is verified; production use still requires configured Service 1 credentials,
  the trusted attestation key, and deployment acceptance. It is not a continuous live feed.
- **Provider selection** — historical retrieval requires an explicit configured
  provider with historical-candle capability; real providers are connection-tested.
  No default test provider or synthetic fallback is used.
- **Frontend** — a dedicated React + TypeScript + Vite dashboard with a typed
  API client, runtime response validation, and accurate loading, empty,
  unavailable, and error states.
- **Operations** — Dockerfiles for both artefacts, a Compose stack, CI for
  tests, linting, type checking, builds, and container checks, and an
  `.env.example` containing placeholders only.

### Service 1 historical dataset attestation verification

The typed Service 1 response now preserves its `provenance` attestation, and
Service 2 verifies the Ed25519 signature against a public-key trust bundle
provisioned out of band before provider-sourced historical replay. Production
replay with Service 1 configured requires
`UPSTREAM_HISTORICAL_ATTESTATION_REQUIRED=true` and a non-empty
`UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` mapping key IDs to base64
raw Ed25519 public keys.

Run `python scripts/export_historical_attestation_public_key.py` in a trusted
Service 1 administrative environment where the historical signing private key
is available. Verify the script's SHA-256 fingerprint out of band and copy
only the public key and exact key ID to Service 2 Railway backend Variables.
Never copy the private key to Service 2. The verified signature authenticates
the configured Service 1 signer and the exact dataset projection; it does not
prove a vendor signature or original historical publication time. Replay
availability therefore remains an explicit candle-close-plus-lag assumption,
and replay output remains `forecast_eligible=false`.

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

The frontend build-time settings are documented in [`frontend/.env.example`](frontend/.env.example). `VITE_API_BASE_URL` selects this service's own backend API base path (default `/api/v1`); `VITE_API_TIMEOUT_MS` sets the browser API client's request timeout in milliseconds (default `8000`). Both are public, non-secret Vite build-time settings: configure them in the Vercel project or local frontend environment, and never place API keys, provider credentials, or other secrets in `VITE_*` variables. Neither value is obtained from an external provider.

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
| `DATABASE_URL` | PostgreSQL connection URL for the lifecycle evidence inbox. Required when the lifecycle consumer is enabled in production; credentials are secret-bearing. Obtain from Railway PostgreSQL Variables; see https://docs.railway.com/guides/postgresql. | Conditional secret-bearing URL |
Use a dedicated PostgreSQL database and a role that owns only that database (or has equivalent DDL/DML rights within its isolated schema). The current inbox adapter bootstraps its own tables, indexes and immutability triggers at startup, so a pure DML-only runtime role will fail initialization. A shared managed PostgreSQL cluster is acceptable, but do not grant cluster-wide ownership/superuser rights or access to another service's database. Keep Service 2 `DATABASE_URL` scoped to its own database.


## GFX Service 9 lifecycle evidence integration — deployment gate

**Status: PROPOSED CONTRACT / CONSUMER IMPLEMENTED BUT DISABLED.** The shared [Liquidity Lifecycle Evidence v1 contract](https://github.com/gavlixdt-tech/fx-api-contracts/tree/main/schemas/liquidity-lifecycle-evidence/v1) is a technical proposal only and is not yet an approved production Service 9→Service 2 contract. This repository contains the authenticated Service 62 consumer, independent signature/source-attestation verification, durable inbox, conflict/quarantine ledger and point-in-time replay integration. It remains disabled until external approval, trust configuration and deployment acceptance. The existing caller-supplied event-study endpoint remains research-only and explicitly reports `provenance_status=caller_asserted_unverified` and `forecast_eligible=false`.

Do not add a Service 9 URL, shared API key, caller-provided producer identity, or manually supplied `available_at` to production and treat it as trusted evidence. Before activation, implementation must include Service 9 authenticated workload identity, independently verifiable event signatures, key rotation/revocation, source lineage, immutable first-availability timestamps, instrument/timeframe/price-basis compatibility, durable deduplication, bounded replay, and leakage tests. A valid JSON Schema or successful HTTP request is not provenance verification.

### Deployment instructions for this boundary

The optional consumer code and exact deployment variables are documented in the section **Service 9 → Service 62 → Service 2 lifecycle evidence consumer** below. Keep the feature disabled until the proposed contract is approved, the Service 62 consumer grant is installed, the Service 9 public key is provisioned out of band, and independent source attestation is available.



## Current implementation and verification snapshot

The latest fully passing Service 2 pipeline is GitHub Actions run
[44388591503](https://github.com/gavlixdt-tech/fx-historical-market-analysis-service/actions/runs/44388591503)
on commit `108005a856a994945f414f20064e20d4e92a46a1`. This run includes
PostgreSQL `TRUNCATE` rejection checks for the inbox, source-verification,
conflict, quarantine and import ledgers:

- Ruff lint and strict format check: passed.
- Mypy: passed.
- Backend tests, including PostgreSQL integration, SQLite cutover, exact CloudEvent envelope identity, append-only quarantine/conflict ledgers and full-source snapshot cutover guards: **250 passed, 2 skipped, 1 warning**.
- Frontend type check, unit tests and production build: passed.
- Backend and frontend container builds: passed.
- Production npm dependency audit: passed; full audit passed under the documented temporary development-only picomatch advisory exception.
- Python dependency and secret audit: passed.
- PostgreSQL restart durability check: passed.

A later CI run found a new high-severity upstream advisory,
[CVE-2026-112366 / GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf),
in `picomatch@4.0.7`, reached through the Vite/Vitest development-tool chain.
The affected packages are development dependencies, not application runtime
dependencies. No patched upstream release was available at the time this
snapshot was updated; the upstream remediation work remains open in
[picomatch PR 237](https://github.com/micromatch/picomatch/pull/237).

A narrow CI policy has been added: production dependencies remain blocking-
audited at high severity, and the full dependency audit permits only this
specific advisory while every affected package is verified absent from the
production dependency tree. This is a documented temporary exception, **not
a claim that the development dependency has been fixed**. The new policy and
script still require a successful CI run on the latest commit.

This validates the earlier Service 2 pipeline, including its PostgreSQL
migration importer and fail-closed legacy SQLite cutover guard; it does **not** mean that Service 64 identity registration,
Admin Console consumer registration, Railway production variables, live
market-provider entitlement, vendor attestation, or deployed cross-service
replay have been completed. Keep production feature flags disabled until
external identity, trust-key, provider-credential and cross-service
acceptance checks are complete.


## Service 9 → Service 62 → Service 2 lifecycle evidence consumer

Service 2 includes an optional authenticated Service 62 consumer with an
independent Ed25519 signature verifier and durable inbox. When `DATABASE_URL`
is set, the consumer selects the PostgreSQL inbox; SQLite remains a local and
backward-compatible fallback. It verifies
the event type, schema version, Service 9 producer identity, key ID, RFC 8785
canonical payload digest, Ed25519 signature, instrument identity, provenance
shape and monotonic event timestamps. It persists accepted events before
acknowledging the Event Bus delivery. Invalid signatures are durably
quarantined and acknowledged so one poison event cannot block the partition.
A repeated event is deduplicated only when its topic, signed payload digest,
and complete canonical CloudEvent envelope are identical; changed unsigned
extension metadata under the same event ID is retained in the conflict ledger.
Reuse of a quarantined
delivery ID with different content or rejection metadata is also recorded as
an immutable conflict instead of being silently discarded.

**Important source-trust boundary:** Service 9 requires and verifies a Service 1 Ed25519 signature over the exact complete candle dataset, then signs its derived lifecycle event. Service 2 independently verifies both signatures and checks that the CloudEvent source, subject, event time, partition, idempotency key, sequence, correlation, causation, quality and provenance headers exactly match the signed lifecycle payload; changing unsigned routing metadata is rejected. This is a Service 1 dataset attestation, not a vendor-origin digital signature. Only events with both signatures verified are source-attested and replay-eligible. If the Service 9 event signature is trusted but the embedded Service 1 attestation key is not yet in Service 2's trust bundle, Service 2 retains the immutable signed event as pending evidence, excludes it from replay, and reports it as `pending_source_attestation_events`. After the approved Service 1 public key is added to `UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` and Service 2 is restarted, replay reads reverify pending attestations and append a separate immutable source-verification record; no broker redelivery or rewrite of the original event is required. Invalid source signatures remain ineligible. Replay additionally requires exact source dataset, instrument, timeframe and price-basis matches, plus both producer availability and Service 2 inbox receipt no later than each prediction origin.

### Railway configuration

Configure these variables in Railway → GFX project →
`fx-historical-market-analysis-service` → backend Variables. In production,
provision PostgreSQL and set `DATABASE_URL` before enabling the consumer.
SQLite fallback is restricted to one active process and must use persistent storage.

For `/api/v1/historical-replay/run-from-market-data`, the request's `source_dataset_id` must equal the `source_id` in the verified Service 1 dataset attestation. The replay path rejects a caller-supplied dataset identifier that does not match the signed attestation. Lifecycle features are selected only for that exact dataset, canonical instrument, mapped timeframe and price basis.

| Variable | Purpose | Where to obtain it | Secret? |
|---|---|---|---|
| `LIFECYCLE_EVENT_BUS_ENABLED` | Enables the background consumer; keep false until Service 62 topic/grants and the trust bundle are configured. | Release gate | No |
| `LIFECYCLE_EVENT_BUS_URL` | Fixed Service 62 backend origin, preferably same-project Railway private DNS with explicit port. | Railway → GFX project → `fx-event-bus-service` → Networking | No |
| `LIFECYCLE_EVENT_BUS_TOPIC` | Exact topic, default `gfx.liquidity.lifecycle.v1`. | Ratified GFX contract and Service 62 topic configuration | No |
| `LIFECYCLE_EVENT_CONSUMER_GROUP` | Stable Service 2 consumer group; default `gfx-service2-lifecycle-evidence`. | Service deployment identity | No |
| `LIFECYCLE_EVENT_BUS_CONSUMER_SECRET` | Dedicated Service 2 consumer HMAC secret; must match Service 62 `HMAC_CONSUMER_SECRETS_JSON`. Generate with `openssl rand -hex 32`. | Generate in a trusted terminal; configure only in Service 2 and Service 62 backend Variables | **Secret** |
| `LIFECYCLE_EVENT_PUBLIC_KEYS_JSON` | JSON map of Service 9 signing key IDs to base64 raw Ed25519 public keys. | Obtain from the approved Service 9 signing-key registry; never copy a private key | Public trust material |\n| `UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` | Service 1 historical dataset signer trust bundle. The consumer verifies the embedded Service 1 dataset attestation independently using this existing trust bundle. | Obtain from Service 1 approved key export and configure in the same backend Variables used by historical attestation verification | Public trust material |
| `DATABASE_URL` | PostgreSQL connection URL for the multi-replica inbox, conflict ledger, quarantine and point-in-time evidence store. | Railway → PostgreSQL service → Variables; reference its private `DATABASE_URL` in Service 2 backend Variables | **Secret-bearing URL** |
| `LIFECYCLE_EVENT_INBOX_DB_PATH` | SQLite fallback path and legacy-state cutover verification path even when PostgreSQL is selected. During migration, keep it pointed at the exact existing SQLite volume file; Service 2 refuses consumer startup if any legacy inbox, source-verification, conflict or quarantine rows were not imported or the WAL-consistent SQLite snapshot fingerprint or per-table counts differ from the import ledger. On a new PostgreSQL-only installation with no legacy file, the path may be non-existent. | Local SQLite development or the existing persistent volume during PostgreSQL cutover | No |
| `LIFECYCLE_EVENT_POLL_INTERVAL_SECONDS` | Poll interval, 0.25–60 seconds; default 2. | Operator tuning | No |
| `LIFECYCLE_EVENT_BATCH_SIZE` | Maximum consumed messages per poll, 1–100; default 25. | Operator tuning | No |
| `LIFECYCLE_EVENT_CLOCK_SKEW_SECONDS` | Maximum future availability tolerance, 0–600 seconds; default 60. | Infrastructure clock policy | No |

### SQLite-to-PostgreSQL inbox cutover

Before switching a deployed Service 2 instance from SQLite to PostgreSQL:

1. Keep `DATABASE_URL` configured for the target PostgreSQL database, but stop
   the Service 2 consumer so no new inbox writes occur during the cutover.
2. Keep Service 62 running; unacknowledged deliveries remain recoverable there.
3. Run the offline importer from the repository root:

   ```bash
   DATABASE_URL='postgresql://…' python backend/scripts/migrate_lifecycle_inbox_sqlite_to_postgres.py \
     --sqlite-path /data/lifecycle-inbox.sqlite3
   ```

4. The importer uses SQLite's online backup API and `PRAGMA integrity_check`
   to capture and validate a consistent WAL snapshot. It verifies each signed
   payload digest, source-dataset index, and both stored UTC epoch-microsecond
   indexes against their ISO-8601 timestamps before import. It verifies
   accepted-event, source-verification and conflict-ledger digests; reconciles
   every indexed metadata field; and imports accepted events, source-verification
   records, conflict history and quarantine records in one PostgreSQL transaction.
   It preserves event IDs and receipt times, advances the conflict-ledger
   sequence after explicit ID imports, and serializes concurrent importers with
   a PostgreSQL advisory lock. Any invalid row, metadata mismatch or conflicting
   existing record aborts the entire transaction; no partial import or source
   fingerprint is committed. The import ledger is database-enforced append-only,
   and the fingerprint prevents repeating an identical successful import.
5. Restart Service 2 with `DATABASE_URL` and `LIFECYCLE_EVENT_INBOX_DB_PATH`
   pointing to the old volume. Startup verifies that all four legacy evidence
   tables were imported before the consumer starts. Verify inbox status, selected
   lifecycle history and point-in-time evidence manifests before re-enabling
   normal consumer traffic.

Do not copy a live SQLite WAL database file with filesystem tools. Preserve
the original SQLite volume as a rollback artifact until the PostgreSQL cutover
and replay verification have been accepted. The importer does not deploy,
delete or modify the source SQLite database.

In Service 62 Railway Variables, configure
`HMAC_CONSUME_GRANTS_JSON` with the Service 2 subject
`fx-historical-market-analysis-service` allowed to consume only
`gfx.liquidity.lifecycle.v1`, and configure the matching generated secret
under `HMAC_CONSUMER_SECRETS_JSON`. Do not reuse the global HMAC key or the
Service 9 producer key.

Verify after deployment with authenticated
`GET /api/v1/forecasting/lifecycle-evidence/status`. The response separates
signature-verified events, source-attested events, conflicts and quarantined
deliveries. `source_attested_events` increases only for events whose Service 9 signature and embedded Service 1 dataset attestation both verify against the configured out-of-band trust bundles. A zero count is expected when the consumer is disabled or no fully attested event has been accepted; never bypass either verifier to increase it.


## Point-in-time lifecycle replay timestamp correctness

Lifecycle evidence is eligible at a prediction origin only when both the
producer-signed data.temporal.available_at instant and the durable Service 2
inbox received_at instant are no later than that origin. Source candle time,
event observation/confirmation time, producer availability, and consumer
receipt are distinct clocks; an earlier candle/event timestamp never
backdates downstream availability.

The inbox replay selector stores and compares exact UTC epoch-microsecond
values for both producer availability and durable consumer receipt. It does
not rely on lexical ISO-8601 TEXT ordering (Z versus +00:00) or SQLite
julianday floating-point precision. The SQLite compatibility adapter
backfills legacy rows at startup; PostgreSQL stores the epoch values as native
BIGINT columns. Event records are ordered by parsed effective
availability max(producer available_at, inbox received_at). Replay cutoffs
must be timezone-aware, are evaluated chronologically, and results are
returned in the caller's original cutoff order. Equal-time events use event ID
as a stable tie-breaker.

Regression coverage includes exact-instant equality across Z and +00:00
representations, a sub-millisecond future-evidence exclusion, out-of-order
replay cutoffs, and rejection of naive timestamps. Run pytest backend/tests/test_lifecycle_evidence.py from the
repository root. This source change is not a substitute for the separate live
Service 9 → Service 62 → Service 2 deployment acceptance test.


## Lifecycle transition identity, history reconstruction and replay evidence

Service 9 lifecycle aggregate identity is distinct from each transition event
identity. Service 2 now requires the signed `lifecycle.transition_id` to match
the CloudEvents/payload event ID and verifies the full transition history:
strict sequence numbering, deterministic transition IDs, monotonic transition
times, previous-hash linkage, each RFC-8785 SHA-256 transition digest, and the
final transition head. Reusing a lifecycle sequence with a different event is
recorded as a conflict; the unique lifecycle/sequence index prevents two
competing heads from silently becoming canonical.

The inbox persists aggregate ID, transition sequence and transition digest
alongside the immutable signed envelope. It keeps duplicate deliveries
idempotent, records event-ID conflicts and lifecycle-sequence forks, and
quarantines invalid signatures or malformed history. A conflict is never
silently overwritten. Legacy inbox rows that predate signed transition chains
are retained for audit but have `source_verified` revoked during migration so
they cannot enter model features.

### Late delivery and prediction-origin evidence manifests

Replay selection is based on the maximum of producer-signed availability and
durable consumer receipt. For each lifecycle, the selector advances only to
a higher verified transition sequence; a late lower-sequence delivery cannot
roll a previously observed lifecycle state backwards. Among eligible
lifecycles, the most recently observed transition is selected deterministically.

The market-data replay response now includes
`reproducibility.lifecycle_evidence` with:

- A deduplicated evidence registry containing immutable event IDs, payload
  digests, lifecycle IDs, transition sequence/head digests, producer
  availability and consumer receipt timestamps.
- A `prediction_origin_evidence` entry for each replay observation origin,
  containing the exact event IDs available at that origin and a SHA-256 digest
  of that evidence set.
- The RFC-8785 manifest algorithm and the precise availability policy.

This makes the evidence inputs auditable and reproducible without embedding
the full signed envelope repeatedly in every prediction row. It does not
promote caller-asserted events to trusted features and does not establish a
vendor-origin signature.

Run the lifecycle evidence tests with:

```bash
pytest backend/tests/test_lifecycle_evidence.py
```

Run the Service 9 transition identity/outbox fencing tests with:

```bash
pytest backend/tests/test_lifecycle_transition_history.py
```

The feature remains research-only. Live provider entitlements, approved
cross-service contract publication, trust-key provisioning and a deployed
end-to-end acceptance run remain separate production gates.


Replay reads now independently re-verify the stored Service 9 Ed25519
signature, embedded Service 1 attestation, canonical payload digest, and
indexed inbox metadata before a lifecycle record can become a feature or
appear in an evidence manifest. A modified/corrupt persisted record fails the
replay closed; the system does not trust the inbox's mutable verification flag
alone. The consumer loads the same configured public trust bundles at startup,
so restart does not weaken replay verification.


Each generated historical replay prediction row also carries its own
`lifecycle_evidence` reference: prediction origin, exact event IDs, evidence
count and evidence-set digest. The run-level registry deduplicates the signed
event metadata while preserving a per-prediction pointer, so the evidence can
be reconstructed without repeating full envelopes in every row.


The authenticated endpoint
`GET /api/v1/forecasting/lifecycle-evidence/{lifecycle_id}/history`
reconstructs the full signed transition chain for an aggregate. It re-verifies
the latest signed head and every individually received transition event before
returning the reconstructed chain, head digest and receipt/availability
records. It returns 404 when no source-attested history is stored and fails
closed when persisted evidence no longer verifies.


Transition-history labels describe canonical milestones, while
`lifecycle.state` describes the aggregate's current state. For example, the
canonical `SWEEP_CONFIRMED` transition maps to aggregate state
`SWEEP_CONFIRMED_AWAITING_DISPLACEMENT`. This separation keeps earlier
transition IDs and hashes stable as the lifecycle advances.


### PostgreSQL and replica boundary

When `DATABASE_URL` is configured, Service 2 uses PostgreSQL with transaction-
scoped advisory locks per lifecycle aggregate, unique lifecycle-sequence
constraints, append-only evidence/conflict/quarantine tables with database
triggers rejecting `UPDATE`, `DELETE` and `TRUNCATE`, and indexed integer UTC
epoch-microsecond cutoffs. The SQLite import ledger also rejects bulk truncation. Concurrent consumers serialize history
fork checks for the same lifecycle while independent lifecycle aggregates can
be ingested concurrently. The SQLite fallback remains single-active-process
only. All three services now provide PostgreSQL persistence adapters. The complete
pipeline is not yet certified for horizontal scaling until Service 9, Service
62 and Service 2 are configured against PostgreSQL, all existing SQLite records
are imported safely, and end-to-end concurrency, restart, conflict and
point-in-time replay acceptance tests pass.

## CI, GHCR and Railway deployment

The canonical delivery pipeline is separated into `ci.yaml`,
`ghcr.yaml` and `railway.yaml`. CI is the mandatory test/validation gate.
After a successful CI run on the default branch, GHCR builds the backend
image using build context `repository root` and Dockerfile `backend/Dockerfile`,
publishes immutable `sha-<commit>` and `latest` tags, and attaches
BuildKit provenance and an SBOM. The Railway workflow triggers the
preconfigured deploy hook only after successful GHCR publication.

Set GitHub Actions secret `RAILWAY_DEPLOY_HOOK_URL` to this Railway
service's deploy hook. Configure Railway to pull
`ghcr.io/gavlixdt-tech/fx-historical-market-analysis-service:latest` or a pinned SHA tag, configure private
GHCR access if required, and set the port and health check to the code-defined
container values. The workflow does not create the Railway service or change
its image source. For browser-facing applications, Vercel is the deployment
target; browsers call only the public API Gateway versioned routes and never
direct service Railway origins.

Use the code-backed environment/provider sections above for runtime setup.
Store all credentials in Railway secrets and keep upstream service traffic on
private networking. Passing CI and publishing an image do not establish
external provider availability, business-level acceptance, disaster recovery,
or production sign-off.

## Complete environment-variable and provider reference

The checked-in [`.env.example`](./.env.example) is the canonical placeholder template. This table inventories every variable assignment in that template; descriptions are taken from the adjacent source comments. Confirm conditional requirements against the runtime settings validators before enabling each feature. Blank template values are intentionally unset and are not valid production credentials.

| Variable | Purpose / configuration note | Requirement | Secret |
|---|---|---|---|
| `SERVICE_NAME` | --------------------------------------------------------------------------- fx-historical-market-analysis-service - environment template PLACEHOLDERS ONLY. Never commit real credentials. Copy to .env for local development; .env is git-ignored. --------------------------------------------------------------------------- ---- Service identity ---- | Optional/defaulted; configure when the feature is used | No |
| `SERVICE_VERSION` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `API_VERSION` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `ENVIRONMENT` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `SERVICE_MODE` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `API_HOST` | ---- Runtime ---- | Optional/defaulted; configure when the feature is used | No |
| `API_PORT` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LOG_LEVEL` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LOG_FORMAT` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `REQUIRE_AUTH` | ---- Inbound security ---- REQUIRE_AUTH must be true in production, and API_KEY must then be set. | Optional/defaulted; configure when the feature is used | No |
| `API_KEY` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional unless required by an enabled production feature | Yes — secret store only |
| `CORS_ALLOW_ORIGINS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `CORS_ALLOW_CREDENTIALS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | Yes — secret store only |
| `CORS_ALLOW_METHODS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `CORS_ALLOW_HEADERS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `TRUSTED_HOSTS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `DOCS_ENABLED_IN_PRODUCTION` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `MAX_REQUEST_BODY_BYTES` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_MARKET_DATA_BASE_URL` | ---- Upstream integration: fx-market-data-service ---- Leave UPSTREAM_MARKET_DATA_BASE_URL empty to run without an upstream. On Railway, use the Service 1 private-network origin, including its port: http://fx-market-data-service.railway.internal:8000 Production allows HTTP only for *.railway.internal with an explicit port; public production upstreams must use HTTPS. | Optional unless required by an enabled production feature | No |
| `UPSTREAM_API_KEY` | Credential presented to Service 1 using X-API-Key. Server-side only. Must match Service 1 MARKET_DATA_CLIENT_API_KEYS_JSON['historical-analysis']. This is a dedicated Service 2 workload identity, not Service 1 API_KEY. Keep it server-side; never expose it to the browser. | Required in the stated production/feature condition | Yes — secret store only |
| `UPSTREAM_HISTORICAL_ATTESTATION_PUBLIC_KEYS_JSON` | Out-of-band Service 1 Ed25519 historical dataset trust bundle. JSON object: {"<Service 1 key_id>":"<base64 raw 32-byte public key>"}. Obtain the public key by running Service 1 scripts/export_historical_attestation_public_key.py in a trusted admin environment; never copy the private signing key. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_HISTORICAL_ATTESTATION_REQUIRED` | Production historical replay requires true and a non-empty trusted key bundle. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_TIMEOUT_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_READ_TIMEOUT_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_MAX_RETRIES` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_RETRY_MAX_DURATION_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_MAX_CONCURRENT_REQUESTS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_MAX_RESPONSE_BYTES` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_CONNECTIVITY_CHECK_ENABLED` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_MAX_HISTORY_LIMIT` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS` | Required for /historical-replay/run-from-market-data. Set a conservative, provider-specific delay; current Service 1 contract has no original publish time. | Optional unless required by an enabled production feature | No |
| `GFX_SETTINGS_ENABLED` | UPSTREAM_ALLOWED_HISTORY_START=2020-01-01T00:00:00Z UPSTREAM_ALLOWED_HISTORY_END=2030-01-01T00:00:00Z ---- GFX Admin Console replay settings ---- Enable only after creating the dedicated Service 2 workload identity in Service 64 and registering it as a required consumer in the Admin Console. When enabled, the integration fails closed: no silent request-parameter fallback. | Optional/defaulted; configure when the feature is used | No |
| `GFX_SETTINGS_REQUIRED` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `GFX_SETTINGS_SERVICE_URL` | Admin Console BACKEND origin, not the browser/Vercel frontend URL. Prefer the Railway private-network origin with explicit service port. | Optional unless required by an enabled production feature | No |
| `FX_SECURITY_SERVICE_URL` | Service 64 BACKEND origin; same private-network guidance as above. | Optional unless required by an enabled production feature | No |
| `GFX_SETTINGS_CLIENT_ID` | Dedicated Service 2 workload identity from Service 64; server-side only. | Optional unless required by an enabled production feature | No |
| `GFX_SETTINGS_CLIENT_SECRET` | Secret shown once by Service 64 when the identity is created; server-side only. | Optional unless required by an enabled production feature | Yes — secret store only |
| `OTEL_ENABLED` | ---- Observability ---- | Optional/defaulted; configure when the feature is used | No |
| `OTEL_ENDPOINT` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional unless required by an enabled production feature | No |
| `METRICS_ENABLED` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `DATABASE_URL` | ---- Shared PostgreSQL persistence ---- Production lifecycle evidence consumption requires this private connection URL. Local SQLite fallback remains available when DATABASE_URL is empty. | Optional unless required by an enabled production feature | No |
| `LIFECYCLE_EVENT_BUS_ENABLED` | ---- Service 62 signed lifecycle evidence consumer ---- Disabled until the producer contract and source-attestation gates are accepted. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_BUS_URL` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional unless required by an enabled production feature | No |
| `LIFECYCLE_EVENT_BUS_TOPIC` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_CONSUMER_GROUP` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_BUS_CONSUMER_SECRET` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional unless required by an enabled production feature | Yes — secret store only |
| `LIFECYCLE_EVENT_PUBLIC_KEYS_JSON` | JSON mapping Service 9 key IDs to base64 raw 32-byte Ed25519 public keys. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_INBOX_DB_PATH` | SQLite compatibility fallback only; single active replica/process. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_POLL_INTERVAL_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_BATCH_SIZE` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |
| `LIFECYCLE_EVENT_CLOCK_SKEW_SECONDS` | Runtime setting consumed by the backend configuration; see the corresponding settings module for defaults and validation. | Optional/defaulted; configure when the feature is used | No |

## External-provider and integration boundary

This service consumes historical market observations from `fx-market-data-service` and verifies the configured Service 1 attestation trust bundle. It does not own market-data vendor credentials. Configure Service 1's private Railway origin, dedicated workload API key and the out-of-band public-key trust bundle in this backend's Railway variables. The browser must call the API Gateway, not this service's Railway URL.
