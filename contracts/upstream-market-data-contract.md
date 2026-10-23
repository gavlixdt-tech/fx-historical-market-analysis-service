# Upstream Integration Contract: `fx-market-data-service`

**Status of this document:** the request/response contract below was
**VERIFIED** by reading the Service 1 source tree directly. The
**authentication** contract is **PROPOSED — NOT YET VERIFIED** and is called
out explicitly in [Authentication](#authentication--proposed--not-yet-verified).

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

### What could NOT be verified

1. **Service 1's OpenAPI document.**
   `fx-market-data-service/docs/api/openapi.yaml` contains only the single
   line `# fx-market-data-service API contract placeholder`. It declares **no
   paths and no security schemes**. Every contract fact below therefore comes
   from the implementation, not from a published specification.

2. **Service 1's production authentication mechanism.**
   Service 1's `backend/app/main.py` installs a middleware stack from a
   shared package named `Pipline` (`Pipline.middleware.AuthMiddleware`,
   `Pipline.middleware.configure_trusted_host_middleware`). That package is
   **not vendored** in the Service 1 repository and **not installed** in its
   virtual environment, so the production authentication behaviour of the
   shared middleware could not be read. Only the local
   `backend/middleware/auth.py` implementation was readable.

3. **The platform API gateway.**
   No gateway repository, gateway configuration, or gateway route table was
   found in either repository. Gateway conventions are documented as
   *proposed* in `docs/architecture.md` and are explicitly **not** implemented
   here.

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

### 4.3 Liveness probe — `GET /api/v1/health/live`

**Verified.** Used by this service only as a connectivity check for the
upstream integration. It is a liveness probe, not a data request.

---

## 5. Authentication — PROPOSED — NOT YET VERIFIED

**This section is explicitly unverified.**

Service 1's local `backend/middleware/auth.py` reads the **`X-API-Key`**
request header and compares it to the configured `api_key` using
`secrets.compare_digest`. When `require_auth` is enabled, a matching header
is required on all paths except the public set
(`/api/v1/health/live`, `/api/v1/health/ready`, `/api/v1/status`,
`/api/v1/version`, `/metrics`, `/api/v1/openapi.json`, `/docs`, `/redoc`,
`/health`).

However:

- Service 1's OpenAPI document declares **no** security scheme.
- Service 1's *deployed* authentication middleware comes from the unvendored
  `Pipline` package, whose behaviour could not be inspected.
- A shared static API key is a plausible local-development mechanism but is
  **not** an acceptable production design for service-to-service traffic.

### What this service does about it

1. The client sends the credential in the `X-API-Key` header **only when a
   credential is configured**. When none is configured, no header is sent and
   the request is simply sent unauthenticated.
2. The credential is read from `UPSTREAM_API_KEY`, is **server-side only**,
   is never returned by any endpoint, and is never sent to the browser.
3. The credential is presented by the **backend only**. The dashboard never
   contacts Service 1.
4. The status endpoint reports `contract_status` so an operator can see
   whether the contract in use is verified.

### Required before production

Before this integration is used in production, the following must be
confirmed and this document updated:

- [ ] Service 1's **real** authentication contract (mTLS, signed service
      token, OAuth2 client credentials, or the platform's chosen
      mechanism).
- [ ] Whether the platform gateway terminates authentication on behalf of
      downstream services, in which case this client would present a
      gateway-scoped credential instead.
- [ ] Credential rotation and expiry behaviour.
- [ ] Per-service authorisation scope (which instruments/providers this
      service may read).

Until those are confirmed, the authentication mechanism in this repository is
**PROPOSED — NOT YET VERIFIED** and must not be treated as final.

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
