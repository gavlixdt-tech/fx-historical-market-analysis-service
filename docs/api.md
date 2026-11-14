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
      { "name": "historical_statistics", "implemented": true, "detail": "Descriptive statistics over historical observations." }
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
      "contract_status": "proposed-not-yet-verified",
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

### `GET /api/v1/data-source`

Returns backend-reported configuration and connectivity for the upstream
market-data service. An unset connectivity result reports the contract as
`proposed-not-yet-verified`; successful reachability does not verify the
production authentication contract.

### `GET /api/v1/historical-data/providers`

Returns the Service 1 provider inventory without credentials. A provider must
be explicitly selected for retrieval. The inventory reports provider type,
configuration, connection status, and historical-candle capability; it is
not evidence of market-data entitlement.

### `POST /api/v1/historical-data/retrieve`

Retrieves a bounded historical dataset through Service 1. `provider_id` is
required. Returns observations, source-quality evidence, provenance, and a
dataset fingerprint. Test providers are explicitly synthetic and available
only in development/testing. A provider type of `real` is not proof of
entitlement or signed source data.

### `POST /api/v1/analysis/regimes`

Runs retrospective rule-based regime classification and change-point analysis.
Regime labels describe the supplied historical sample; change-point detection
uses the full series and is retrospective, not a point-in-time signal.

### `POST /api/v1/analysis/patterns`

Runs bounded historical pattern research. Supported pattern IDs are
`volatility_compression_expansion`, `directional_persistence`, and
`reversal_after_large_move`. Supported overlap policies are `allow`,
`min_gap`, and `no_overlap_outcome`. Unsupported pattern IDs and overlap
policies are rejected rather than silently treated as empty results or
`allow`.

The chronological walk-forward summary purges training events whose target
horizon would reach the test period and excludes test events without a complete
future horizon. Pattern effects and permutation statistics remain exploratory;
they do not establish a deployable forecast or trading edge.

### `POST /api/v1/analysis/research-summary`

Combines the retrospective regime and pattern research outputs into one
descriptive summary. It does not calculate calibrated forecast confidence.

### `GET /api/v1/analysis/capabilities`

Returns the implemented historical-analysis algorithms, features and supported
pattern identifiers.

### `POST /api/v1/research/readiness`

Validates whether an `ExperimentRunRequest` is ready to run, including experiment validation, dataset quality and coverage checks.

### `POST /api/v1/analysis/seasonality`

Runs descriptive calendar-seasonality research over contiguous historical
close-to-close returns. The request requires an explicit `timeframe` and accepts
an optional provider ID or caller-supplied observations, a supported `price_basis`, an IANA `timezone`,
and one or more `bucket_types`: `weekday`, `hour_of_day`, and `month_of_year`.

Each return is assigned to the local calendar bucket of the ending candle
timestamp. Returns spanning more than `maximum_gap_multiple` times the declared
timeframe are excluded and counted rather than treating a multi-period move as
a single-period return. The response reports bucket counts, mean/median return,
positive-return rate, realized volatility, average candle range, difference
from the global mean, and a deterministic circular moving-block bootstrap
interval for adequately sampled buckets. The response includes an effective
configuration and a deterministic analysis fingerprint derived from the dataset
fingerprint and all seasonality settings.

`minimum_bucket_samples` labels descriptive sample sufficiency; it is not a
statistical significance threshold. The endpoint does not produce p-values,
forecast probabilities, trading signals, or model-approved features. Results
remain subject to the returned data-provenance limitations.

### `GET /api/v1/forecasting/models`

Lists supported model families, optionally filtered by `task_type`.

### `POST /api/v1/forecasting/experiment/validate`

Validates an experiment configuration without executing it.

### `POST /api/v1/forecasting/experiment/run`

Executes a forecasting experiment and returns fold, model, comparison,
aggregate, warning and limitation data. Caller-supplied `data_source` and
`synthetic` fields are recorded only as declarations; they cannot establish
provider origin. Caller-supplied observations are returned as
`user_supplied_unverified`, with unknown synthetic status unless explicitly
declared synthetic.

### `POST /api/v1/historical-replay/run`

Runs the point-in-time historical replay described in
[`historical-replay.md`](historical-replay.md). The request supplies 40–2,000
chronologically ordered observations (the actual minimum is derived from the
lookback, training minimum, horizon, and embargo), each with a timezone-aware
`timestamp`, `available_at`, OHLCV values, and `source_record_id`; it also
supplies instrument, timeframe, source dataset ID, and a forecasting problem.

The response contains the ordered out-of-sample predictions, baseline and
model-family metrics, regime-conditioned summaries, classification
calibration diagnostics where applicable, block-bootstrap comparison,
supplementary White's Reality Check / PBO diagnostics, dataset fingerprint,
and explicit warnings/limitations. `available_at` and provenance identity are
caller-supplied and unverified. Results are not persisted. No trades, costs,
or profitability are simulated.

The API rejects records whose availability precedes their observation,
non-chronological/duplicate observation timestamps, or availability order
that moves backward. CPU-bound replay runs in a worker thread; request-body
size remains bounded by `MAX_REQUEST_BODY_BYTES`.

### `POST /api/v1/historical-replay/run-from-market-data`

Accepts the same replay options with provider ID, instrument, timeframe, price
basis, date range, and source dataset ID instead of an observations array.
Service 2 retrieves validated candles through the configured Service 1 client.
Only a configured real provider with an available connection and historical
candle capability is accepted. Partial/incomplete coverage, invalid candles,
or truncated responses are rejected.

The endpoint requires `UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS` and derives
each `available_at` from `close_time + delay`. The current Service 1 contract
does not provide original publication timestamps, so the resulting evidence
is always marked `provider_asserted_unverified`; it is not proof of historical
information availability. See [`historical-replay.md`](historical-replay.md)
for configuration and limitations.

No broker, execution, or order endpoints are exposed.
