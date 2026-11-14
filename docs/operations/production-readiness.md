# Production readiness

**Decision: BLOCKED.** The current repository supports local
research/simulation; passing unit tests or building the frontend does not
establish production readiness.

| Gate | Status | Evidence / blocker |
|---|---|---|
| Service 1 request/response shape | PASS WITH EXPLICIT LIMITATIONS | Source-mirrored typed schemas and labelled contract fixtures; production auth is not verified |
| Real provider selection | PASS WITH EXPLICIT LIMITATIONS | Explicit provider ID, configured/capability checks, connection test; no entitlement or live provider response verified here |
| Source quality | PASS WITH EXPLICIT LIMITATIONS | Coverage, validation, and pagination metadata preserved; source claims are not independently attested |
| Historical availability | BLOCKED | Provider first-available timestamp absent; replay uses configured close-plus-lag assumption |
| Point-in-time replay | PASS WITH EXPLICIT LIMITATIONS | UTC, ordering, OHLC, availability, maturity, purge/embargo and chronological checks; historical source availability/revisions remain unverified |
| Service 60 durable artifacts | BLOCKED | No typed client or approved lineage-compatible envelope |
| Service 61 shared features | BLOCKED | No approved equivalent point-in-time contract |
| Service 63 runtime handoff | BLOCKED | Source schemas reviewed; no authenticated end-to-end run or approved workload identity |
| Services 21/49/50 | BLOCKED / NOT_IMPLEMENTED | No compatible data handoff; Service 21 fitted forecasting remains unavailable |
| Service 62 event delivery | BLOCKED | No approved production transport, publisher identity, or consumer acknowledgement |
| Service 64 identity | BLOCKED | No approved Service 2 workload identity/grant |
| Service 65 centralized observability | BLOCKED | Local metrics and optional OTEL exist; central ingestion/authorization/propagation unverified |
| Service 66 recovery | BLOCKED | No durable artifact service integration or tested restore |
| Frontend | PASS WITH EXPLICIT LIMITATIONS | Typed backend-only API, OHLC chart/table, provenance, historical regime/pattern research, calendar seasonality, direction-calibration controls, replay context and caller-supplied event-study workspace; durable experiment history and automatic upstream event ingestion remain unavailable |
| CI/container/deployment | NOT_VERIFIED | Local checks do not prove CI, container runtime, or a deployed environment |
| Trading/execution | NOT_APPLICABLE | Service 2 is research-only and has no order-placement adapter |

Production prerequisites include approved Service 64 inbound/outbound
identity, verified Service 1 auth and TLS trust, real provider entitlement,
historical availability lineage or accepted caveat policy, durable artifact
contract and tested recovery, and a cross-service deployment smoke test.

Do not set `ENVIRONMENT=production` as a means of testing real-provider
retrieval: Service 2 deliberately blocks real-provider reads until the
approved workload identity/grant exists.
