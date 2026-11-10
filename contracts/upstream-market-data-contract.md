# Upstream Integration Contract: `fx-market-data-service`

**Status of this document:** request/response contracts and Service 1's
authentication-required status field were verified against the Service 1
source tree. Service 2 now verifies the runtime status response and the
protected provider inventory before reporting its upstream as connected.
Production workload identity and authorization remain unverified; see
[Authentication](#authentication-and-runtime-verification).

- **Contract verified on:** 2026-10-22
- **Verified against:** `C:\Users\ian mai\fx-market-data-service\backend\`
- **Consumed by:** `backend/app/clients/market_data.py`
- **Typed schemas:** `backend/app/schemas/upstream.py`

---

## 1. Why this service does not own market data

`fx-market-data-service` (Service 1) remains the **authoritative upstream
source** for market observations. It owns:

- external provider integration and credential management,
- quote normalisation and validation,
- historical and real-time data access,
- data provenance, freshness, and source-quality reporting.

This service (Service 2) must **not** duplicate any of the above. It may
*inspect* Service 1's quality metadata and *reject* unsuitable analytical
inputs, but it never re-validates or re-prices the underlying observations.

---

## 2. Verification method and its limits

The following were read directly from the Service 1 source:

| Item | Source file read |
| --- | --- |
| Route paths and query parameters | `backend/app/api/v1/routes/market_data.py` |
| Router mounting (`/api/v1` prefix) | `backend/app/api/v1/router.py` |
| Response envelope | `backend/schemas/common.py` |
| Historical payload schema | `backend/schemas/market_data.py` |
| Error envelope | `backend/core/errors.py` |
| Correlation ID handling | `backend/middleware/correlation.py` |
| API key header handling | `backend/middleware/auth.py` |
| Timeframe / price basis enums | `backend/domain/market_data.py` |
| Provider connectivity test route and result | `backend/app/api/v1/routes/market_data.py`, `backend/schemas/market_data.py` |

### What could NOT be verified

1. **Service 1's OpenAPI document.**
   `fx-market-data-service/docs/api/openapi.yaml` contains only the single
   line `# fx-market-data-service API contract placeholder`. It declares **no
   paths and no security schemes**. Every contract fact below therefore comes
   from the implementation, not from a published specification.

2. **Deployed workload identity and authorization.**
   Service 1's current source implements `backend/middleware/auth.py` and
   validates the `X-API-Key` header using constant-time comparison. The
   source-level API-key contract is verified. Repository inspection cannot
   prove that deployed Railway secrets match, that credentials are rotated,
   or that workload identity and per-service authorization scopes are
   enforced in the deployed environment.

3. **Deployed gateway connectivity.**
   The Gateway source now registers Service 1, forwards its versioned routes
   (including the streaming feed), strips caller-supplied credentials, and
   injects `MARKET_DATA_API_KEY` server-side. This source-level integration is
   verified; actual Railway deployment, private DNS reachability, and secret
   parity require deployment-environment verification.

---

## 3. Base URL and routing

Service 1 mounts its versioned router under `/api/v1`:

```
GET /api/v1/market-data/...
```

The upstream base URL is supplied to this service through the
`UPSTREAM_MARKET_DATA_BASE_URL` environment variable. **No hostname is
hard-coded**, and no production address is committed to the repository.

The client joins the configured base URL with the verified path below. If the
gateway fronts Service 1, the base URL would point at the gateway route that
forwards to Service 1 — that routing is a gateway concern, not this
service's.

---

## 4. Verified endpoints

### 4.1 Historical candles — `GET /api/v1/market-data/history/{instrument}`

**Verified.** Query parameters (all optional unless noted):

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `provider_id` | string | `test-adapter` | Upstream provider identifier |
| `start` | string | – | ISO-8601 UTC start timestamp |
| `end` | string | – | ISO-8601 UTC end timestamp |
| `timeframe` | string | `D1` | `M1 M5 M15 M30 H1 H4 D1 W1 MN1` |
| `price_basis` | string | `bid` | `bid`, `ask`, `midpoint` |
| `limit` | integer | `500` | Bounds: `ge=1`, `le=5000` |

Path parameter: `{instrument}` — a canonical instrument identifier. The exact
identifier vocabulary is **not** documented by Service 1 and was not verified;
this service passes the identifier through unchanged.

**Path-segment encoding note (verified by implementation):** Service 1's
route is mounted as `/api/v1/market-data/history/{instrument}` and a forward
slash cannot appear inside a single path segment, so Service 1's
canonicaliser accepts the underscore form (`EUR_USD`) and returns the
canonical slash form (`EUR/USD`) in `canonical_instrument`. This client
therefore normalises any `/` in the requested instrument to `_` before
building the path, while leaving an already-underscore form unchanged, so
either input form is supported.

**Response** — standard envelope:

```json
{
  "data": {
    "provider_id": "...",
    "canonical_instrument": "...",
    "requested_start": "...", "requested_end": "...",
    "effective_start": "...", "effective_end": "...",
    "timeframe": "D1",
    "price_basis": "bid",
    "candles": [ { "open_time": "...", "open": "...", "...": "..." } ],
    "coverage": {
      "requested_start": "...", "requested_end": "...",
      "actual_start": "...", "actual_end": "...",
      "expected_intervals": 0, "returned_count": 0,
      "valid_count": 0, "rejected_count": 0, "duplicate_count": 0,
      "missing_intervals": [], "status": "complete",
      "complete": true, "provider_limited": false, "notes": []
    },
    "validation_summary": {
      "total_received": 0, "valid": 0, "rejected": 0, "duplicates": 0
    },
    "pagination": { "limit": 500, "has_more": false },
    "retrieved_at": "...",
    "limitations": []
  },
  "meta": { "api_version": "v1", "request_id": "...", "timestamp_utc": "..." },
  "errors": []
}
```

**Quality metadata ownership.** `coverage`, `validation_summary`, and
`limitations` are Service 1's source-quality output. This service consumes
them for the sole purpose of *rejecting unsuitable analytical inputs* in a
later phase. It does not recompute them.

### 4.2 Provider listing — `GET /api/v1/market-data/providers`

**Verified.** Returns an envelope whose `data` is a **bare JSON array** of
provider summaries — *not* an object wrapping a `providers` key.

Service 1 declares the route as `ApiResponse[list[ProviderSummarySchema]]`
and returns `ApiResponse(data=providers, meta=...)`, where `providers` is a
Python list. Because `ApiResponse.data` is typed `T | None` with
`T = list[ProviderSummarySchema]`, the serialised `data` is the list itself.
Service 2 therefore models it as `list[UpstreamProviderSummary] | None`.

Each provider summary carries `provider_id`, `provider_type`, `configured`,
`connection_status`, `capabilities`, `last_connection_test_*`,
`last_quote_retrieved_at`, `last_error`, and rate-limit fields.

`provider_type`, `connection_status`, and each entry of `capabilities` are
enumerated in Service 2 (mirroring Service 1's
`backend/domain/market_data.py`), so an unrecognised value is rejected rather
than silently accepted:

| Field | Service 1 source | Values |
| --- | --- | --- |
| `provider_type` | `ProviderType` | `real`, `test` |
| `connection_status` | `ProviderConnectionStatus` | `not_configured`, `configured_not_tested`, `available`, `unavailable`, `authentication_failed`, `rate_limited`, `unknown` |
| `capabilities[]` | `ProviderCapability` | `connection_test`, `instrument_discovery`, `latest_quote`, `historical_candles`, `streaming`, `rate_limit_info` |

Service 1 guarantees this endpoint never returns credentials. The client
re-validates that property in a contract test.

> **Drift corrected on 2026-10-22.** Service 2 previously expected
> `data.providers` (an object envelope) and would have rejected every real
> Service 1 providers response. The correction is covered by a regression
> test that asserts the obsolete object shape is now rejected.

### 4.3 Provider connectivity test — `POST /api/v1/market-data/providers/{provider_id}/test-connection`

**Verified.** Service 2 calls this endpoint only after confirming the selected
provider is configured, is of type `real`, and advertises historical-candle
capability. It requires a successful response whose `data.provider_id` matches
the requested provider and whose `data.success` is true before fetching data.
The response carries provider ID, success, latency, start/completion times,
message, and request ID. This is an active provider connectivity test and may
update Service 1's provider test status; it is not merely a Service 1 liveness
probe.

### 4.4 Liveness probe — `GET /api/v1/health/live`

**Verified.** This endpoint reports process liveness only. Service 2 does not
use it to report upstream integration readiness because it cannot prove that
the protected contract or a real data provider is available.

### 4.5 Authentication policy — `GET /api/v1/status`

**Verified.** This public endpoint returns the versioned response envelope.
Service 2 validates its `api_version`, request ID, timestamp, empty errors,
and `data.api_key_authentication_required` boolean before using the declared
policy to decide whether a credential is required for the protected provider
inventory request. The status endpoint itself is called without the upstream
API key.

---

## 5. Authentication and runtime verification

Service 1's public `GET /api/v1/status` response declares whether API-key
authentication is required. Service 2 reads that policy without sending a
credential, then requests the protected provider inventory using its
server-side credential. An accepted provider-inventory response proves that
the configured credential is accepted by the Service 1 instance reached by
that check. Missing or rejected credentials are reported distinctly.
Connectivity is reported as connected only when the inventory also includes
a configured real historical-candle provider whose latest connection test
succeeded and has a UTC timestamp. That upstream test timestamp is displayed
separately from Service 2's own status-check time.

Service 1's local `backend/middleware/auth.py` reads the **`X-API-Key`**
request header and compares it to the configured `api_key` using
`secrets.compare_digest`. When `require_auth` is enabled, a matching header
is required on all paths except the public set
(`/api/v1/health/live`, `/api/v1/health/ready`, `/api/v1/status`,
`/api/v1/version`, `/metrics`, `/api/v1/openapi.json`, `/docs`, `/redoc`,
`/health`).

However, a successful local check does not establish deployed workload
identity or production authorization. In particular:

- Service 1's OpenAPI document declares **no** security scheme.
- Deployed workload identity, credential rotation, and per-service
  authorization grants remain unverified; source-level API-key validation
  alone does not establish those controls.

### What this service does about it

1. The client reads the public auth policy first and does not send its
   credential to the public status endpoint. It sends `X-API-Key` only on the
   protected provider-inventory call.
2. The credential is read from `UPSTREAM_API_KEY`, is **server-side only**,
   is never returned by any endpoint, and is never sent to the browser.
3. The credential is presented by the **backend only**. The dashboard never
   contacts Service 1.
4. The connectivity report identifies authentication, contract, and real
   provider evidence separately, including the upstream provider-test time.
   A configured test adapter, a merely configured real provider, or liveness
   alone does not produce a connected status.

### Required before production

Before this integration is used in production, the following must be
confirmed and this document updated:

- [ ] Verify Railway deployment connectivity and private DNS between Service 2,
      the Gateway, and Service 1.
- [ ] Confirm identical secret value is provisioned as Service 1 `API_KEY`,
      Gateway `MARKET_DATA_API_KEY`, and Service 2 `UPSTREAM_API_KEY`.
- [ ] Verify credential rotation and expiry behaviour without downtime.
- [ ] Verify deployed workload identity and per-service authorization scope
      (which instruments/providers this service may read).

Until those are confirmed, local authentication evidence must not be
represented as proof of production/deployed identity or authorization.

---

## 6. Error handling

**Verified.** Service 1 returns errors in the envelope:

```json
{ "error": { "code": "...", "message": "...", "request_id": "...", "details": {} } }
```

Status codes observed in Service 1's implementation:

| Code | Meaning |
| --- | --- |
| `409` | `provider_not_configured`, `unsupported_historical_capability` |
| `502` | `provider_error` (upstream provider failed) |
| `401` | Missing or invalid API key |

This service converts every upstream failure into an internal
`UpstreamError` (HTTP `502`, code `DEP_UPSTREAM_ERROR`) and **never echoes
the upstream body verbatim**, so that upstream topology or credential detail
cannot leak through this service's public API.

---

## 7. Correlation and trace propagation

**Verified.** Service 1 propagates `X-Request-ID` / `X-Correlation-ID` and
echoes them back on the response.

This service therefore:

- reads the inbound `X-Request-ID` / `X-Correlation-ID` (sanitised and
  length-bounded),
- forwards it to the upstream on every request,
- echoes it on every response,
- includes it in the `meta.request_id` field of every envelope,
- uses it as the trace correlation attribute when OpenTelemetry is enabled.

---

## 8. Fixtures used in contract tests

The JSON files in `backend/tests/contract/fixtures/` are **hand-written
synthetic fixtures**. They are not market data, are not derived from observed
market data, and are labelled accordingly in a `_fixture_notice` field. See
`backend/tests/contract/fixtures/README.md`.

---

## 9. Change control

If Service 1's contract changes:

1. Update `backend/app/schemas/upstream.py` (the typed mirror).
2. Update `backend/app/clients/market_data.py` (paths, parameters, bounds).
3. Update the fixtures and contract tests.
4. Update this document, including the verification date and the
   verification status of the authentication section.
