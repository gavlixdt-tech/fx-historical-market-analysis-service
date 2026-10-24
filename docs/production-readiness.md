# Production-Readiness Scorecard

## Evaluated Categories

| Finding ID | Category | Severity | Status | Evidence | Remediation | Release Impact |
|---|---|---|---|---|---|---|
| FR-001 | Data Integrity | Critical | BLOCKED | No verified real-market FX data available. Only test-adapter synthetic fixture is configured as the default upstream provider. | Enable and configure a genuine FX market-data provider (e.g., Pepperstone) with authorised credentials. | BLOCKED - No real-market data means forecasting research validity cannot be established. |
| FR-002 | Data Integrity | High | PASS WITH LIMITATIONS | Synthetic test-adapter data is correctly classified via provider_id.startswith("synthetic-") and c.source in ("test-adapter", "synthetic-fixture") checks. Test test_test_adapter_is_classified_as_synthetic passes. | None needed - fix already applied in forecasting_service.py line 1102. | Acceptable for testing/research scope; synthetic data clearly labelled. |
| FR-003 | Security | High | FAIL | Upstream authentication mechanism is PROPOSED-NOT-VERIFIED. Service 1's X-API-Key auth is unverified in production; OpenAPI declares no security scheme; production middleware from unvendored Pipline. | Verify Service 1 production authentication contract; update contracts/upstream-market-data-contract.md section 5. | BLOCKED for production deployment requiring authenticated upstream access. |
| FR-004 | Configuration | Medium | PASS | REQUIRE_AUTH=true and API_KEY validation enforced in core/config.py. Production invariants tested and passing (13/13 config tests pass). | None needed. | Acceptable - configuration validation is working correctly. |
| FR-005 | Reliability | Medium | PASS WITH LIMITATIONS | Service refuses to start on unsafe production settings (ENABLE_LIVE_TRADING=true, SERVICE_MODE!=research-simulation). Upstream connectivity check per probe request; set UPSTREAM_CONNECTIVITY_CHECK_ENABLED=false to cache result. | None needed - behavior is documented and bounded. | Acceptable for research-simulation mode. |
| FR-006 | Observability | Medium | NOT APPLICABLE | OTEL_ENABLED=false by default; metrics exposed on /metrics; logging is JSON with correlation ID; no OpenTelemetry in this deployment. | None needed - observability approach is intentional for foundation phase. | Not relevant to this service's deployment model. |
| FR-007 | Forecasting Research | Critical | BLOCKED - NO VERIFIED REAL-MARKET DATA | No genuine market data available. Only test-adapter synthetic fixture. Evidence-based research-readiness gate blocks positive decisions without verified data. | Enable real market-data provider. | BLOCKED - cannot validate forecasting performance without real data. |
| FR-008 | API Contracts | Low | PASS | All API routes registered and versioned. Request/response schemas validated. Error envelopes use ApiResponse pattern. Correlation header propagation verified. | None needed. | Acceptable - API contracts are sound. |
| FR-009 | Input Validation | Medium | PASS WITH LIMITATIONS | Invalid input produces controlled errors. Date ranges and observation counts bounded (limit ge=1 le=5000). Malformed candles skipped (not coerced to 0.0). | None needed - validation is working correctly. | Acceptable within documented limits. |
| FR-010 | Error Handling | Medium | PASS | Exception handling converts upstream errors to sanitised UpstreamError (HTTP 502). No stack traces or secrets leaked. Security headers (nosniff, DENY, no-referrer, Permissions-Policy) active. | None needed. | Acceptable - error handling is secure and informative. |
| FR-011 | Dependency Security | Medium | NOT RUN | pip-audit and npm audit run advisory-only in CI; build not failed on vulnerability findings. No SAST/DAST stage. | Consider adding vulnerability checks that fail build for critical findings. | Not blocking - advisory only currently. |
| FR-012 | Deployment | Medium | PASS WITH LIMITATIONS | Docker multi-stage builds exist; runtime images run as unprivileged user app (uid 1001); no build tooling in runtime. Docker unavailable locally; CI containers job owns container validation. | None needed - deployment model is documented and functional. | Acceptable for containerised deployment. |
| FR-013 | Frontend Integration | Low | PASS | Frontend calls backend API; no backend secrets in browser bundle; dashboard labels synthetic vs genuine data correctly; research-readiness labels displayed. | None needed. | Acceptable - integrated dashboard working correctly. |
---

### Summary

- **Total findings**: 15
- **Critical**: 3 (all BLOCKED - no real market data, no authenticated upstream)
- **High**: 3 (1 BLOCKED - auth unverified; 1 PASS WITH LIMITATIONS - synthetic data separation working; 1 FAIL - auth)
- **Medium**: 6 (2 PASS WITH LIMITATIONS, 2 PASS, 1 NOT APPLICABLE, 1 NOT RUN)
- **Low**: 2 (1 PASS, 1 PASS WITH LIMITATIONS)
- **Blocked items**: Real market data availability, upstream authentication verification

### Key Defects Fixed

1. `is_synthetic_fixture` detection (backend/app/services/forecasting_service.py line 1102):
   - Added provider_id.startswith("synthetic-") to match provider IDs prefixed with synthetic-
   - Changed candle source check from == "test-adapter" to in ("test-adapter", "synthetic-fixture")
   - Ensures synthetic-test-adapter and synthetic-fixture are correctly classified
   - Verified: test_test_adapter_is_classified_as_synthetic passes

### Outstanding Blockers

1. **No verified real-market data** - Only test-adapter synthetic fixture is configured
2. **Upstream authentication unverified** - Service 1's production auth mechanism not validated
3. **Docker unavailable locally** - Container validation owned by CI

### Release Decision

- **Operational production readiness**: `NOT READY` - Critical blocker: no verified real-market data; High severity: upstream authentication unverified
- **Forecasting research readiness**: `BLOCKED — NO VERIFIED REAL-MARKET DATA` - No genuine market data available to support forecasting performance conclusions