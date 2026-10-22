# Security

This service is a private, internal research service. It handles no customer
funds, places no orders, and holds no trading credentials. Its security
posture is therefore about protecting internal topology, credentials, and the
integrity of analytical inputs.

## 1. Controls implemented

| Control | Where | Notes |
| --- | --- | --- |
| Configuration validation | `backend/app/core/config.py` | Fail-fast on unsafe production settings. |
| Inbound API key | `backend/app/middleware/auth.py` | `X-API-Key`, constant-time compare, public-path allowlist. |
| CORS allowlist | `main.py` | Explicit origins only; wildcard rejected in production. |
| Trusted hosts | `main.py` (`TrustedHostMiddleware`) | Only known hosts are served. |
| Security headers | `backend/app/middleware/security.py` | `nosniff`, `DENY`, `no-referrer`, `Permissions-Policy`. |
| Request size limit | `backend/app/middleware/security.py` | `MAX_REQUEST_BODY_BYTES`, default 1 MiB. |
| Safe error responses | `backend/app/core/errors.py` | No stack traces, no internal hostnames. |
| Secret redaction | Response schemas | No credential field exists in any response schema. |
| Correlation IDs | `backend/app/middleware/correlation.py` | Sanitised and length-bounded. |
| Non-root containers | `backend/Dockerfile`, `frontend/Dockerfile` | Dedicated unprivileged user (uid 1001). |
| Log redaction | `backend/app/core/logging.py` | Only the path is logged, never the query string. |
| Live-trading lockout | `core/config.py` | `ENABLE_LIVE_TRADING=true` refuses to start. |
| Mode lockout | `core/config.py` | `SERVICE_MODE` must be `research-simulation`. |

### Enforced production invariants

The application refuses to start when any of these hold in production:

- `REQUIRE_AUTH` is not `true`.
- `API_KEY` is empty while `REQUIRE_AUTH` is `true`.
- `CORS_ALLOW_ORIGINS` contains `*`.
- `ENABLE_LIVE_TRADING` is `true` (in any environment).
- `SERVICE_MODE` is not `research-simulation` (in any environment).

These are enforced in `Settings._validate_security_invariants` and covered by
tests in `backend/tests/unit/test_config.py`.

## 2. Secret handling

- `.env.example` contains **placeholders only**. No real value is committed.
- `.env` and `.env.*` are git-ignored (except `.env.example`).
- `API_KEY` and `UPSTREAM_API_KEY` are read from the environment only.
- No response schema contains a credential field, so there is no code path
  that could serialise one.
- The dashboard never receives a credential. The backend presents the upstream
  credential server-side only.
- CI runs a grep check for possible hard-coded credentials and fails the job if
  one is found.

## 3. Upstream authentication — PROPOSED — NOT YET VERIFIED

Service 1's local middleware reads an `X-API-Key` header, but its OpenAPI
document is a placeholder with no security schemes, and its production
middleware comes from an unvendored `Pipline` package. A shared static API key
is **not** assumed to be the correct production design.

The full analysis, the risks, and the pre-production checklist are in
`contracts/upstream-market-data-contract.md`, section 5.

**Before production, the real Service 1 authentication mechanism must be
verified and this document updated.** The mechanism currently implemented is a
placeholder that satisfies the verified request/response contract only.

## 4. Gateway

No gateway is implemented in this repository. The service is designed so that a
gateway can sit in front of it without the service knowing:

- the upstream base URL is configuration, not code;
- correlation and trace headers follow the platform conventions;
- the service remains fully functional and independently deployable with no
  gateway present.

Gateway-specific authentication termination is **PROPOSED — NOT YET VERIFIED**
because no gateway repository was available to inspect.

## 5. Container hardening

- Both images are multi-stage; build tooling is not present in the runtime
  image.
- Both run as a dedicated unprivileged user (uid/gid 1001).
- Neither image contains source control metadata or a `.env` file.
- The backend image declares a `HEALTHCHECK` against the liveness endpoint.
- The frontend image serves static files through nginx as a non-root user.

## 6. Known limitations

1. **Upstream authentication is unverified.** See section 3.
2. **No rate limiting.** The gateway is expected to provide it. Nothing in
   this repository throttles inbound requests.
3. **No audit log of privileged actions.** There are no privileged actions in
   this phase: the API is read-only.
4. **No dependency pinning by hash.** Python dependencies are pinned to version
   ranges rather than exact hashes. The npm lockfile pins exact versions.
5. **No SAST/DAST stage.** CI runs `pip-audit` and `npm audit`, but neither
   result currently fails the build; they are advisory only.

## 7. Reporting a vulnerability

Report privately to the platform engineering team. Do not open a public
issue. Do not include credentials, tokens, or market data in the report.
