# Deployment Guide

## 1. Deployment model

This service is **independently deployable**. It has no build-time or
run-time dependency on Service 1: the upstream integration is optional and its
base URL is configuration.

Two deployable artefacts:

| Artefact | Path | Result |
| --- | --- | --- |
| Backend | `backend/Dockerfile` | FastAPI service on port 8000. |
| Frontend | `frontend/Dockerfile` | Static bundle served by nginx on port 8080. |

## 2. Container builds

```bash
docker build -f backend/Dockerfile -t fx-historical-market-analysis-service-backend:latest .
docker build -f frontend/Dockerfile -t fx-historical-market-analysis-service-frontend:latest .
```

Both are multi-stage. The runtime images contain no build tooling and run as
the unprivileged user `app` (uid 1001).

## 3. Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

The frontend proxies `/api/` to the backend. The browser therefore never
learns the backend's address, and the upstream market-data service is not
reachable from the browser at all.

## 4. Required production configuration

| Variable | Production value | Reason |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | Enables the strict invariants. |
| `REQUIRE_AUTH` | `true` | The service refuses to start otherwise. |
| `API_KEY` | secret, injected at runtime | Inbound authentication. |
| `CORS_ALLOW_ORIGINS` | the dashboard's exact origin | Wildcards are rejected. |
| `TRUSTED_HOSTS` | the hostnames the gateway forwards | Host-header protection. |
| `DOCS_ENABLED_IN_PRODUCTION` | `false` unless required | Hides the OpenAPI document. |
| `LOG_FORMAT` | `json` | Structured logs for the shipper. |
| `UPSTREAM_MARKET_DATA_BASE_URL` | the in-cluster address or gateway route | Server-side only. |
| `UPSTREAM_API_KEY` | secret, injected at runtime | **Unverified mechanism — see below.** |

Secrets must be injected by the platform's secret manager. They must not be
baked into an image, committed to the repository, or passed on the command
line of a long-running process.

### Production startup validation

The service refuses to start when:

- `REQUIRE_AUTH` is not `true`;
- `API_KEY` is empty while `REQUIRE_AUTH` is `true`;
- `CORS_ALLOW_ORIGINS` contains `*`;
- `ENABLE_LIVE_TRADING` is `true`;
- `SERVICE_MODE` is not `research-simulation`.

This is intentional: a misconfigured deployment fails immediately and
visibly instead of serving traffic unsafely.

## 5. Health probes

| Probe | Path | Success |
| --- | --- | --- |
| Liveness | `/api/v1/health/live` | HTTP 200 |
| Readiness | `/api/v1/health/ready` | HTTP 200 (503 when degraded) |
| Container | `/api/v1/health/live` | HTTP 200 |

Readiness returns 503 when the upstream market-data service is unreachable.
In this foundation phase that only degrades the service; it does not make it
unready, because no analytical capability depends on the upstream yet.

## 6. Observability

### Metrics

`GET /metrics` exposes Prometheus text format on a dedicated registry
(`fx_hma_*` metric names):

| Metric | Type | Meaning |
| --- | --- | --- |
| `fx_hma_service_up` | gauge | 1 while the process runs. |
| `fx_hma_http_requests_total` | counter | Requests by method, path, status. |
| `fx_hma_http_request_duration_seconds` | histogram | Request latency. |
| `fx_hma_upstream_requests_total` | counter | Upstream calls by outcome. |
| `fx_hma_upstream_last_check_succeeded` | gauge | Last upstream check result. |

### Tracing

Set `OTEL_ENABLED=true` and `OTEL_ENDPOINT` to an OTLP HTTP collector to
enable OpenTelemetry export. Tracing is off by default, and a collector
failure can never prevent the service from starting.

### Logging

JSON, one object per line, with the correlation ID on every record. The
request path is logged; the query string is not.

## 7. Gateway placement

The service can sit behind the platform gateway without knowing. The gateway
owns routing, TLS termination, rate limiting, and (if the platform decides
so) inbound authentication.

The upstream base URL may point at a gateway route or directly at Service 1.
Nothing in the internal modules assumes either.

**The gateway route table is PROPOSED — NOT YET VERIFIED** because no gateway
repository was available to inspect. See `docs/architecture.md` section 8.

## 8. Scaling

The service is stateless: no session state, no in-process cache, no
persistence. The backend can be scaled horizontally behind the gateway.

The optional upstream connectivity check in the readiness probe is performed
per probe request. If that becomes a bottleneck, set
`UPSTREAM_CONNECTIVITY_CHECK_ENABLED=false` and rely on the cached result
from the status endpoint.

## 9. Rollback

Deploy the previous image tag. There is no database migration to reverse
because no database is provisioned in this phase.

## 10. Pre-production checklist

- [ ] `ENVIRONMENT=production`, `REQUIRE_AUTH=true`, and a strong `API_KEY`.
- [ ] `CORS_ALLOW_ORIGINS` contains only the real dashboard origin.
- [ ] `TRUSTED_HOSTS` matches the hostnames the gateway forwards.
- [ ] `DOCS_ENABLED_IN_PRODUCTION=false`.
- [ ] Secrets injected from the secret manager, not from a file in the image.
- [ ] **Service 1's real authentication contract verified** and
      `contracts/upstream-market-data-contract.md` updated. See
      `docs/security.md` section 3.
- [ ] The gateway route for this service confirmed.
- [ ] Monitoring and alerting on `/api/v1/health/ready` and
      `fx_hma_upstream_last_check_succeeded`.
