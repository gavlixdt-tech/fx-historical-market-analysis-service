# Prompt 11 — Real-Market Data Integration, Verified Upstream Contract & End-to-End Acceptance

## 1. Initial repository state
- Repository: `fx-historical-market-analysis-service`
- Branch: `master`
- HEAD at start: `105b12e22724df1fb64c6ca8fbcb50ee834e2229` (`feat: strengthen reproducible forecasting validation`)
- Working tree at start: clean.
- Commit `105b12e` exists in history: yes.
- Service 1 repository was later found locally at `C:\\Users\\ian mai\\fx-market-data-service` (`main` @ `02876d780550eaa43daacee686b7f936e7aa6707`) with a modified working tree. It was inspected read-only and not modified.

## 2. Upstream contract verification matrix
| Integration detail | Status | Evidence |
| --- | --- | --- |
| Upstream base URL / deployment | UNAVAILABLE for production address; VERIFIED for local runtime | No hostname committed. `UPSTREAM_MARKET_DATA_BASE_URL` was unset in Service 2. A local Service 1 instance was started at `http://127.0.0.1:8001` for a bounded live check. |
| Service health endpoint | VERIFIED | `GET /api/v1/health/live` returned HTTP 200 with `{"status":"healthy",...}` from the local Service 1 instance. |
| Historical-data endpoint and method | VERIFIED | Service 1 route `GET /api/v1/market-data/history/{instrument}` inspected in `backend/app/api/v1/routes/market_data.py`; live request returned HTTP 200 and 5 candles. |
| Instrument/timeframe/date/price-basis params | VERIFIED | Route signature and live request `provider_id=test-adapter&timeframe=D1&price_basis=bid&limit=5` succeeded. |
| Candle response schema/timestamp semantics | VERIFIED | `backend/schemas/market_data.py` `HistoricalCandleSchema`; live response parsed by Service 2 `UpstreamHistoricalCandle`. |
| Error response format/status codes | PARTIALLY VERIFIED | Service 1 app errors use `{"error":{"code","message","request_id","details"}}`; route validation errors are FastAPI `HTTPException` details and are stringified by Service 1's handler. Service 2 does not echo upstream bodies. |
| Authentication requirements | PROPOSED — NOT VERIFIED | Service 1 local `AuthMiddleware` reads `X-API-Key` when `require_auth=true`; default is false. Production middleware comes from unvendored `Pipline`; OpenAPI declares no security scheme. |
| Credential source/safe config | VERIFIED (mechanism) | Service 2 reads `UPSTREAM_API_KEY` server-side only; never returned to browser; `.env.example` uses placeholders. |
| Correlation IDs | VERIFIED | Service 1 propagates `X-Request-ID`/`X-Correlation-ID`; live request echoed IDs. |
| Pagination/limits/timeouts | VERIFIED (bounds) | `limit` ge=1 le=5000; Service 2 enforces the same. Bounded connect/read/write/pool timeouts with retries. |
| Upstream data-quality guarantees | VERIFIED (synthetic test adapter) | Service 1 test adapter returns 5 deterministic fixture candles with `source=test-adapter` and fixture metadata. It is explicitly not real market data. |
| Client matches verified contract | VERIFIED | Mock contract tests pass; live historical request parsed successfully. |

## 3. Changes made
- `backend/app/services/forecasting_service.py`: detect synthetic test-adapter fixtures during upstream retrieval; set `synthetic` and provenance accordingly; improve experiment provenance from declared input origin.
- `backend/app/schemas/forecasting.py`: add optional `data_source` and `synthetic` fields to `ExperimentRunRequest`.
- `frontend/src/features/RealMarketDataWorkspace.tsx`: pass retrieved dataset origin and synthetic flag into experiment runs.
- `frontend/src/features/ForecastingReadiness.tsx`: label the synthetic demo experiment explicitly.
- `backend/tests/integration/test_prompt11_integration_validation.py`: add mock-based validation for missing config, timeout, refusal, upstream errors, malformed payloads, correlation, no fallback, empty responses, and guarded live test.
- `.env.example`: expand upstream configuration inventory with placeholders.
- `docs/prompt11-integration-evidence.md`: this report.

## 4. Local software validation
- New Prompt 11 mock tests added.
- Existing backend and frontend suites remain the regression baseline.
## 5. Contract validation
- Contract tests: `backend/tests/contract/test_upstream_contract.py` (shape validation against labelled synthetic fixtures).
- Service 1 source was available locally and re-inspected for routes, auth, schemas, correlation, and error handling.
- OpenAPI at Service 1 remains a placeholder; contract facts come from implementation, not a published spec.

## 6. Live upstream test results
- Service 1 was started locally at `http://127.0.0.1:8001` without modifying it.
- `MarketDataClient.check_connectivity()` returned `CONNECTED`, latency 2163.66 ms, checked at 2026-10-23T09:19:49Z.
- `fetch_historical_candles("EURUSD", provider_id="test-adapter", timeframe="D1", price_basis="bid", limit=5)` returned canonical instrument `EUR/USD`, 5 candles, validation valid count 5, coverage complete false.
- Provider listing returned `test-adapter`.
- The returned candles are deterministic test-adapter fixture data, not real market observations.

## 7. Real-market-data research status
- BLOCKED for real-market research.
- The only available upstream provider is `test-adapter`, whose candles are explicitly labelled deterministic test data.
- Pepperstone provider is disabled and unconfigured; no credentials are available.
- Therefore no real-data experiment was run and no synthetic result is presented as real-market evidence.

## 8. Security and architectural boundary checks
- Service 1 was not modified.
- No duplicate provider adapter was created.
- No credentials appear in frontend code, logs, fixtures, or this report.
- Upstream errors are converted to sanitised `UpstreamError` (HTTP 502) without echoing upstream bodies.
- Synthetic vs real provenance is labelled; retrieved test-adapter data is marked synthetic.

## 9. Remaining blockers and required evidence
1. A real market-data provider (for example Pepperstone) must be enabled and configured with authorised credentials.
2. Service 1 production authentication (mTLS/signed token/OAuth2 or gateway-enforced auth) must be verified; current `X-API-Key` remains proposed.
3. A permitted instrument, bounded date range, and safe test environment must be approved.
4. Provider provenance/quality metadata must be validated against live real data.

## 10. Test and Git state
- Backend tests, lint, type checks, frontend tests, and production build were run after changes.
- Live upstream check completed against the local Service 1 instance.
- Real-market research remains blocked.
PY
PY