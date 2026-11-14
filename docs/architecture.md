# Architecture

## 1. Purpose

`fx-historical-market-analysis-service` (Service 2) is the second microservice
in the Forex AI platform. Its responsibility is to analyse historical
foreign-exchange market observations in order to discover statistically
defensible historical patterns, market regimes, temporal relationships, and
other evidence-supported findings.

**This repository provides research/simulation capabilities, including
retrospective regime/pattern analysis, calendar seasonality, availability-aware
historical replay, a caller-supplied session/liquidity event-timing study, and an optional provider-sourced replay path.** It does not provide production model serving, authenticated cross-service
prediction ingestion, or trading.

---

## 2. System context

```mermaid
graph TB
    Operator["Operator / Researcher"]
    Browser["Dashboard (browser)"]

    subgraph Service2["fx-historical-market-analysis-service (this repo)"]
        FE["React + TypeScript dashboard<br/>(frontend/)"]
        BE["FastAPI backend<br/>(backend/app)"]
        Client["MarketDataClient<br/>(typed upstream client)"]
    end

    Gateway["Platform API Gateway<br/>(separate service)"]
    Service1["fx-market-data-service<br/>(Service 1, external repo)"]
    Provider["External market-data providers<br/>(Service 1's responsibility)"]

    Operator --> Browser
    Browser -->|"same-origin /api"| BE
    BE -->|"server-side only"| Client
    Client -->|"upstream contract"| Gateway
    Gateway --> Service1
    Service1 --> Provider

    style Gateway stroke-dasharray: 5 5
    style Service1 stroke-dasharray: 5 5
```

### Boundary rules

| Rule | Enforcement |
| --- | --- |
| The browser never calls Service 1 | The dashboard only knows `VITE_API_BASE_URL`, which points at this service's own backend. `frontend/nginx.conf` proxies only `/api/` to `backend:8000`. |
| This service never owns provider credentials or feed code | Provider credentials and provider calls remain inside Service 1. Service 2 uses only its server-side Service 1 credential. |
| Provider-sourced replay requires an explicit availability assumption | Current Service 1 candles contain close times but no original publication timestamps; Service 2 records `close_time + configured lag` as assumed availability and does not claim point-in-time proof. |
| Market data quality authority remains Service 1 | The upstream client validates contract shape and checks coverage, while source validation metadata is retained from Service 1. |
| The gateway remains a separate service | The gateway can route Service 63; Service 2 is not itself an API gateway or browser identity authority. |

---

## 3. Repository layout

```text
fx-historical-market-analysis-service/
├── backend/
│   ├── app/
│   │   ├── api/v1/            # Versioned routing
│   │   │   ├── router.py      # Aggregates the v1 routers
│   │   │   └── routes/        # health.py, status.py, version.py
│   │   ├── core/              # config.py, errors.py, logging.py
│   │   ├── middleware/        # auth, correlation, request_logging, security
│   │   ├── schemas/           # Request/response contracts (incl. upstream.py, replay.py)
│   │   ├── clients/           # market_data.py: typed upstream client
│   │   ├── services/          # forecasting_service.py, health_service.py
│   │   ├── analysis/          # point-in-time features, models, replay, metrics, seasonality
│   │   ├── observability/     # metrics.py, tracing.py
│   │   └── main.py            # create_app() factory + entrypoint
│   │                          (no repositories/ package: nothing is persisted)
│   ├── tests/
│   │   ├── unit/              # config, correlation, errors, upstream client
│   │   ├── integration/       # HTTP contract behaviour
│   │   ├── contract/          # Upstream payload shapes + labelled fixtures
│   │   └── security/          # auth, headers, size limits, trusted hosts
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/               # App shell, data hook, styles
│   │   ├── components/        # Reusable presentation components
│   │   ├── features/          # Overview, replay, forecasting, integration, diagnostics
│   │   ├── schemas/           # Zod runtime validation schemas
│   │   ├── services/api/      # Typed API client
│   │   └── tests/             # Vitest suites
│   ├── package.json
│   └── Dockerfile
├── contracts/
│   └── upstream-market-data-contract.md   # VERIFIED + unverified sections
├── docs/                      # This file, api, security, dev, deployment, audit
├── .github/workflows/ci.yml
├── compose.yaml
├── .env.example
└── README.md
```

Every module exists for a stated purpose. There are no placeholder modules.

---

## 4. Backend module responsibilities

| Module | Responsibility | Does NOT |
| --- | --- | --- |
| `core/config.py` | Validate environment configuration; fail fast on unsafe production settings. | Read secrets from files. |
| `core/errors.py` | Normalise every failure into one error envelope with a stable code. | Leak exception internals. |
| `core/logging.py` | Emit structured JSON logs with the correlation ID attached. | Log credentials or query strings. |
| `middleware/correlation.py` | Sanitise and propagate `X-Request-ID` / `X-Correlation-ID`. | Trust an unbounded client-supplied ID. |
| `middleware/auth.py` | Enforce the inbound API key on non-public paths. | Log or echo the presented key. |
| `middleware/security.py` | Security headers and request body size limits. | Be disabled in production. |
| `schemas/upstream.py` | Typed mirror of the Service 1 payload shapes. | Re-interpret market data semantics. |
| `clients/market_data.py` | Server-side calls to Service 1 with timeouts, correlation propagation, and sanitised errors. | Be called from the browser. |
| `services/health_service.py` | The single source of truth for operational state. | Report a state it has not observed. |
| `observability/metrics.py` | Prometheus-compatible metrics on a dedicated registry. | Expose default process metrics. |
| `observability/tracing.py` | Optional OpenTelemetry instrumentation. | Prevent startup when the collector is down. |
| `main.py` | `create_app()` factory: wiring, middleware order, exception handlers. | Contain business logic. |

### Middleware order

Starlette runs the most recently added middleware first, so the registration
order in `main.py` yields this request flow:

```text
SecurityHeaders -> RequestLogging -> RequestSizeLimit -> TrustedHost
-> CORS -> CorrelationID -> Auth -> routes
```

Correlation ID runs inside auth so that a 401 response still carries a
correlation ID.

---

## 5. Frontend module responsibilities

| Module | Responsibility |
| --- | --- |
| `app/App.tsx` | Shell, layout, and the read-only framing of the dashboard. |
| `app/useServiceStatus.ts` | Loads status, readiness, and version independently so one failure does not hide the others. |
| `components/` | Reusable presentation: badges, panels, loading, empty, error states. |
| `features/ServiceOverview.tsx` | Service identity, version, connectivity, readiness. |
| `features/AnalysisWorkspace.tsx` | Historical-analysis and replay workspaces. |
| `features/DataSourceIntegration.tsx` | Upstream identity and the real connection state. |
| `features/OperationalDiagnostics.tsx` | Safe diagnostics, correlation IDs, refresh time. |
| `schemas/api.ts` | Zod schemas mirroring the backend contracts. |
| `services/api/client.ts` | Typed client: timeout, runtime validation, normalised errors. |

---

## 6. Current capabilities

Implemented in this phase:

- Application factory with validated configuration and safe production invariants.
- Versioned API routing under `/api/v1`.
- `GET /api/v1/health/live`, `/ready`, `/status`, `/version`.
- Prometheus metrics at `/metrics`.
- Structured JSON logging, OpenTelemetry tracing (opt-in).
- Consistent error envelopes and request correlation IDs.
- A typed, read-only upstream client for the source-verified Service 1 route
  and payload shapes; production authentication remains unverified.
- Explicit provider inventory and selection; synthetic test providers are
  restricted to development/testing and labeled synthetic.
- Historical regime classification, retrospective change-point detection, bounded pattern research, calendar-seasonality distributions, and a separate caller-supplied session/liquidity event-timing study.
- Forecasting research experiments using chronological walk-forward evaluation.
- Historical replay at successive point-in-time origins using explicit
  observation-availability timestamps, target-maturity purging and optional
  embargo.
- Reproducibility fingerprints, out-of-sample metrics, calibration summaries,
  heuristic regime slices, and supplementary selection-bias diagnostics.
- A workbench that consumes caller-provided JSON observations and displays
  replay evidence and its limitations.
- A dedicated React/TypeScript dashboard with validated loading, empty,
  unavailable, and error states.

## 7. Remaining limitations

The replay and research endpoints do not provide:

- independent verification of data provenance and availability timestamps,
- historical revisions/correction event reconstruction,
- immutable durable replay and model-artifact persistence,
- point-in-time outputs from other GFX services and service-level ablation,
- authenticated inter-service replay coordination,
- integrity controls proving that a declared final holdout was never inspected,
- evaluation on future data not used in the replay,
- broker, execution, transaction-cost, and trading simulation.

The replay returns only results calculated from submitted observations and
marks synthetic fixtures or caller-asserted provenance explicitly. It does not
assert that a replayed model was the model used by GFX at the historical time.

---

## 8. Gateway integration

**PROPOSED — NOT YET VERIFIED.** No gateway repository, configuration, or route
table was found in either the Service 1 repo
table was found in either the Service 1 repository or this one, so no gateway
route is invented here.

The design keeps the gateway concern at the edge:

- This service mounts its own API at `/api/v1` and can be reached directly.
- The upstream base URL is configurable, so the same build can point at a
  gateway route or at Service 1 directly.
- Internal modules contain **no** gateway-specific routing; only the client
  knows how to reach the upstream.
- Correlation and trace propagation use the platform conventions verified in
  Service 1 (`X-Request-ID` / `X-Correlation-ID`).
- The dashboard's own path to the backend may terminate at the gateway, but
  the gateway never proxies to Service 1 on the browser's behalf.

---

## 9. Persistence

No database is provisioned. Replay reports and model artifacts are not stored,
and Service 1 remains the owner of the source data. `DATABASE_URL` exists in
the configuration only so that a later, separately justified phase can add
persistence without changing the configuration shape. See
`docs/acceptance-audit.md` for the justification required before that phase.

## 10. Current integration boundary

Service 2 rejects real-provider reads in production until an approved Service
64 workload identity/grant is available. Service 1's production authentication
contract is also unverified. Provider-retrieved replay derives availability
from candle close plus a configured lag and labels it `availability_assumed`;
this is not historical publication-time proof.

Service 2 has no Service 60 persistence, Service 61 feature-service adapter,
Services 21/49/50 dataset handoff, Service 62 publisher, or Service 66 recovery
integration. Local metrics and optional OpenTelemetry are not evidence of
central Service 65 ingestion. See the
[`current ecosystem audit`](integration/service2-ecosystem-integration-audit.md).
