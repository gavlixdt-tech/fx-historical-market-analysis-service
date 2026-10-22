# Acceptance Audit — Foundation Phase

This document records the acceptance criteria for the foundation phase, the
evidence for each, and any blocked or unverified item.

**Scope reminder:** this phase delivers the service *foundation*. The
historical analysis engine is **not** implemented.

---

## 1. Acceptance criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Service 2 exists as an independent repository or a verified local repository ready to publish. | **MET (local)** | Independent repository at `C:\Users\ian mai\fx-historical-market-analysis-service`, initialised with `git init`, own history, own CI. **No remote was created or verified** — see section 3. |
| 2 | Its backend foundation is implemented. | **MET** | `backend/app/` — factory, versioned routing, config validation, correlation IDs, error envelopes, health/readiness/status/version, observability, security. 62 tests pass. |
| 3 | Its dedicated frontend dashboard is integrated and functional. | **MET** | `frontend/` — React 18 + TypeScript + Vite, four panels, typed client with runtime validation. 19 tests pass; production build succeeds. |
| 4 | Backend and frontend contracts are validated. | **MET** | Shared Zod schemas mirror the Pydantic schemas; the frontend client validates every response at runtime; a test asserts the dashboard calls only its own backend. |
| 5 | The upstream integration contract is verified or clearly marked unverified. | **PARTIAL** | Request/response contract **VERIFIED** against Service 1 source. **Authentication contract is PROPOSED — NOT YET VERIFIED** and is labelled as such in the code, the contract document, and the status response. |
| 6 | Service 1's responsibilities have not been duplicated. | **MET** | No provider SDK, no feed code, no source-quality engine. The upstream client is read-only and does not re-validate or re-price observations. |
| 7 | No fabricated market information or analytical results are presented. | **MET** | No analysis endpoint exists. Deferred capabilities are reported with `implemented: false`. Contract fixtures are labelled synthetic. A dashboard test asserts no volatility/score/signal text is rendered. |
| 8 | Security and configuration safeguards are implemented. | **MET** | See `docs/security.md` section 1. Production invariants fail fast. Non-root containers. `.env.example` contains placeholders only. |
| 9 | Tests and CI are configured, with actual execution results reported honestly. | **MET** | See sections 2 and 4 below. |
| 10 | Documentation and architecture diagrams are present. | **MET** | `README.md`, `docs/architecture.md` (with Mermaid diagrams), `docs/api.md`, `docs/security.md`, `docs/development.md`, `docs/deployment.md`, `docs/acceptance-audit.md`, `contracts/upstream-market-data-contract.md`. |
| 11 | The service remains independently deployable. | **MET** | No build-time or run-time dependency on Service 1. Two standalone Dockerfiles and a Compose stack. |
| 12 | No trading, prediction,
 or strategy capabilities have been added. | **MET** | No trading, prediction, or strategy code exists. `ENABLE_LIVE_TRADING=true` refuses to start. The dashboard exposes no trading controls, and a test asserts their absence. |

---

## 2. Tests actually executed

All results below were produced locally in this working environment
(Windows, Python 3.15.1, Node 24.20.0).

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `pytest backend/tests -q` | **62 passed** (exit 0) |
| Backend lint | `ruff check backend` | **All checks passed** (exit 0) |
| Backend format | `ruff format --check backend` | **48 files already formatted** (exit 0) |
| Backend types | `mypy backend/app` | **Success: no issues found in 33 source files** (strict mode, exit 0) |
| Frontend tests | `npx vitest run` | **19 passed** (2 files, exit 0) |
| Frontend types | `npx tsc --noEmit` | **Passed** (exit 0) |
| Frontend build | `npm run build` | **Passed** (exit 0) - 55 modules, `dist/index.html` 0.62 kB, JS 213.27 kB (gzip 62.68 kB), CSS 6.30 kB (gzip 1.84 kB) |
| Live smoke test | `TestClient` against all four endpoints | **All returned 200**; correlation ID echoed; capabilities reported truthfully |

The only check that could **not** be executed locally is the container build
(see section 3.4).

### Backend test breakdown

| Suite | File | Covers |
| --- | --- | --- |
| unit | `test_config.py` | Configuration validation, production invariants. |
| unit | `test_correlation.py` | Correlation ID generation, sanitisation, propagation. |
| unit | `test_errors.py` | Error envelope shape, safe 500. |
| unit | `test_upstream_client.py` | Upstream paths, parameters, timeouts, error sanitisation. |
| integration | `test_health_api.py` | Health, status, version, metrics, absence of analysis routes. |
| contract | `test_upstream_contract.py` | Upstream payload shapes against labelled fixtures. |
| security | `test_auth.py` | Auth boundaries, no key leakage, security headers, CORS. |
| security | `test_request_limits.py` | Body size limit, trusted hosts. |

### Frontend test breakdown

| Suite | File | Covers |
| --- | --- | --- |
| tests | `apiClient.test.ts` | Only own backend is called, runtime validation, normalised errors, no credential headers. |
| tests | `dashboard.test.tsx` | Loading, empty, unavailable, and error states; no fabricated analytics; no trading controls. |

---

## 3. Blocked and unverified items

### 3.1 BLOCKED — no verified remote repository

A remote named `fx-historical-market-analysis-service` could not be verified
as existing or created. The local repository is complete and ready to publish.
See `README.md` for the exact publish commands.

Note: the sibling repository in this workspace is named
`fx-historical-analysis-service` (without "market"). The requested name for
this service is `fx-historical-market-analysis-service`. The new repository
uses the requested name and is completely separate from the sibling.

### 3.2 BLOCKED — upstream authentication contract unverified

Service 1's OpenAPI document is a placeholder with no security schemes, and
its production middleware lives in an unvendored `Pipline` package. The
`X-API-Key` mechanism implemented here is therefore marked
**PROPOSED — NOT YET VERIFIED** everywhere it appears. The full analysis and
the pre-production checklist are in
`contracts/upstream-market-data-contract.md` section 5.

### 3.3 BLOCKED — gateway conventions unverified

No gateway repository, configuration, or route table was found. The gateway
integration is documented as **PROPOSED** and is deliberately not implemented.

### 3.4 BLOCKED — container build check not executed locally

Docker was not available in this working environment, so the Dockerfiles were
**not** built and the container smoke test was **not** run locally. The CI
job `containers` performs both. The Dockerfiles and `compose.yaml` are
syntactically reviewed but unbuilt.

### 3.5 Not applicable — no database

No database was provisioned because no analytical results are stored in this
phase. The justification required before a later phase adds persistence is
recorded in `docs/architecture.md` section 9.

---

## 4. Items still to confirm

- [ ] `docker compose build` and the container smoke test (Docker unavailable
      locally; the CI `containers` job performs both).
- [ ] CI run on a pushed branch.
- [ ] The upstream authentication contract, once Service 1 publishes a real
      OpenAPI document (section 3.2).
- [ ] The platform gateway route table (section 3.3).

---

## 5. Phase boundary

This phase deliberately stops at the foundation. The following are **not**
implemented and require explicit authorisation before any work begins:

- historical statistics and descriptive measures,
- pattern and relationship discovery,
- market regime and volatility characterisation,
- statistical strength and limitation evaluation,
- reproducible analytical results with provenance,
- any persistence of analytical results,
- any trading, prediction, or strategy capability.
