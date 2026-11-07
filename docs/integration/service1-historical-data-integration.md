# Service 1 historical-data integration

## Ownership and routes

Service 1 (`fx-market-data-service`) remains the sole owner of provider
credentials, provider connectivity, normalization, collection, and source
quality. Service 2 is a read-only consumer of these verified source routes:

| Operation | Route |
|---|---|
| Liveness | `GET /api/v1/health/live` |
| Provider inventory | `GET /api/v1/market-data/providers` |
| Provider connection test | `POST /api/v1/market-data/providers/{provider_id}/test-connection` |
| Historical candles | `GET /api/v1/market-data/history/{instrument}` |

Historical query parameters are `provider_id`, `start`, `end`, `timeframe`,
`price_basis`, and `limit`. Service 2 validates the typed response envelope,
provider/timeframe/price-basis identity, coverage, validation summary,
pagination, and candle fields. The browser only calls Service 2.

## Provider and instrument policy

No default provider is configured. A retrieval request must provide a
registered, configured provider that advertises `historical_candles`.
Real-provider requests also require a successful Service 1 connection test.
Test providers are permitted only in development/testing, are explicitly
labelled synthetic, and cannot be used for provider-sourced replay.

The approved instruments are those in `surveillance-instruments/1`:
`XAU/USD`, `EUR/USD`, `GBP/USD`, `USD/JPY`, `USD/CHF`, `USD/CAD`, `AUD/USD`,
and `NZD/USD`. Provider replay requires canonical slash-delimited identifiers.
Timeframes are limited to Service 1's declared timeframe enum and price bases
to `bid`, `ask`, and `midpoint`.

The client uses bounded timeouts/retries, a concurrency limit, a response
byte limit, URL-encoded instrument paths, and disabled redirects. Service 1
remains the source-quality authority; Service 2 preserves the returned
coverage/validation fields and applies a separate analysis eligibility policy.

## Availability and provenance

The current Service 1 history schema reports candle open/close times and a
retrieval time, but no independently verified original publication or first
availability time and no stable immutable source-record ID.

Provider replay therefore requires
`UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS` and derives
`available_at = close_time + configured delay`. The output labels this
`availability_assumed`, records the assumption and retrieval times, and
derives a source-record identity from provider, instrument, timeframe, price
basis, candle open time, and source label. This derived identity is not a
provider-issued record ID or signature.

## Authentication and live verification

Service 1's local `X-API-Key` middleware does not prove the production
authentication contract. The production middleware/trust chain and Service 64
outbound grant remain unverified. Service 2 reports the upstream contract as
`proposed-not-yet-verified` until a check supplies otherwise, and refuses
real-provider use from `ENVIRONMENT=production` while the approved Service 64
workload identity/grant is unavailable.

Local contract/provider tests use explicitly labelled synthetic fixtures. No
real provider entitlement or provider response is claimed by this document.
