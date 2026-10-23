# API Reference

Base path: `/api/v1`
OpenAPI: `/api/v1/openapi.json` (interactive docs at `/docs`, `/redoc`).
In production the OpenAPI document and the interactive docs are disabled unless
`DOCS_ENABLED_IN_PRODUCTION=true`.

## Response envelope

Every successful response uses the platform envelope, verified against
`fx-market-data-service`:

```json
{
  "data": { "...": "..." },
  "meta": {
    "api_version": "v1",
    "request_id": "fx-...",
    "timestamp_utc": "2026-01-01T00:00:00Z"
  },
  "errors": []
}
```

`meta.request_id` is the correlation ID. It is also echoed in the
`X-Request-ID` and `X-Correlation-ID` response headers.

## Error envelope

Every failure uses one shape:

```json
{
  "error": {
    "code": "VAL_INVALID",
    "message": "Request validation failed.",
    "request_id": "fx-...",
    "details": { "fields": [] }
  }
}
```

| Code | HTTP | Meaning |
| --- | --- | --- |
| `VAL_INVALID` | 400 / 422 | Request or payload validation failed. |
| `unauthenticated` | 401 | Missing or invalid API key. |
| `HTTP_404` | 404 | Route not found. |
| `VAL_REQUEST_TOO_LARGE` | 413 | Body exceeded `MAX_REQUEST_BODY_BYTES`. |
| `SVR_INTERNAL` | 500 | Unhandled error. The detail is never disclosed. |
| `DEP_UPSTREAM_ERROR` | 502 | The upstream market-data service failed. |
| `SVR_UNAVAILABLE` | 503 | The service cannot currently serve the request. |

## Authentication

When `REQUIRE_AUTH=true`, every endpoint except the public set requires an
`X-API-Key` header matching the configured `API_KEY`.

Public paths: `/api/v1/health/live`, `/api/v1/health/ready`, `/api/v1/status`,
`/api/v1/version`, `/metrics`, `/api/v1/openapi.json`, `/docs`, `/redoc`,
`/health`.

## Endpoints

### `GET /api/v1/health/live`

Liveness. Confirms the process is running. Performs no dependency checks.

```json
{
  "data": {
    "status": "healthy",
    "service": "fx-historical-market-analysis-service",
    "mode": "research-simulation",
    "check": "liveness"
  },
  "meta": { "api_version": "v1", "request_id": "fx-...", "timestamp_utc": "..." },
  "errors": []
}
```

### `GET /api/v1/health/ready`

Readiness. Returns HTTP 200 when healthy and HTTP 503 when degraded.

```json
{
  "data": {
    "status": "healthy",
    "service": "fx-historical-market-analysis-service",
    "mode": "research-simulation",
    "check": "readiness",
    "dependencies": [
      { "name": "fx-market-data-service", "healthy": true, "detail": "..." }
    ]
  },
  "meta": { "api_version": "v1", "request_id": "fx-...", "timestamp_utc": "..." },
  "errors": []
}
```

### `GET /api/v1/status`

Full operational status, the capability manifest, and the upstream
integration state.

```json
{
  "data": {
    "service_id": "fx-historical-market-analysis-service",
    "application_version": "0.1.0",
    "api_version": "v1",
    "environment": "production",
    "service_mode": "research-simulation",
    "operational_state": "operational",
    "uptime_seconds": 1234.5,
    "capabilities": [
      { "name": "service_health", "implemented": true, "detail": "..." },
      { "name": "historical_statistics", "implemented": false, "detail": "Deferred: ..." }
    ],
    "dependencies": [ { "name": "fx-market-data-service", "healthy": false, "state": "unconfigured" } ],
    "upstream_integration": {
      "service": "fx-market-data-service",
      "state": "unconfigured",
      "base_url_configured": false,
      "credential_configured": false,
      "base_url": null,
      "last_checked_at": null,
      "last_check_succeeded": null,
      "last_check_message": null,
      "contract_status": "verified",
      "latency_ms": null
    },
    "timestamp_utc": "2026-01-01T00:00:00Z"
  },
  "meta": { "api_version": "v1", "request_id": "fx-...", "timestamp_utc": "..." },
  "errors": []
}
```

#### Upstream state vocabulary

| State | Meaning |
| --- | --- |
| `unconfigured` | No upstream base URL is set. Nothing has been contacted. |
| `unverified` | A base URL is set but no check has run yet. |
| `connected` | The last check reached the upstream and succeeded. |
| `unavailable` | The last check could not reach the upstream. |
| `auth_failed` | The upstream rejected the configured credential. |

### `GET /api/v1/version`

```json
{
  "data": {
    "service": "fx-historical-market-analysis-service",
    "application_version": "0.1.0",
    "api_version": "v1",
    "environment": "production",
    "service_mode": "research-simulation"
  },
  "meta": { "api_version": "v1", "request_id": "fx-...", "timestamp_utc": "..." },
  "errors": []
}
```

### `GET /metrics`

Prometheus text exposition format. Not part of the OpenAPI document.

### `GET /health` and `GET /`

Legacy aliases retained for infrastructure compatibility. Not part of the
OpenAPI document.

## Not implemented in this phase

No endpoint returns historical analysis results. Requests to paths such as
`/api/v1/analysis/*`, `/api/v1/trading`, or `/api/v1/orders` return `404`
with the standard error envelope. A test asserts this.

### `GET /api/v1/data-source`

Returns backend-reported configuration and connectivity for the upstream market-data service.

### `POST /api/v1/historical-data/retrieve`

Retrieves a bounded historical dataset through the verified Service 2 client. Returns observations, quality findings, provenance and a dataset fingerprint. `synthetic` is `false` for upstream data.

### `POST /api/v1/research/readiness`

Validates whether an `ExperimentRunRequest` is ready to run, including experiment validation, dataset quality and coverage checks.

### `GET /api/v1/forecasting/models`

Lists supported model families, optionally filtered by `task_type`.

### `POST /api/v1/forecasting/experiment/validate`

Validates an experiment configuration without executing it.

### `POST /api/v1/forecasting/experiment/run`

Executes a forecasting experiment and returns fold, model, comparison, aggregate, warning and limitation data. Experiment results may include `data_source`, `synthetic` and `data_provenance`.
